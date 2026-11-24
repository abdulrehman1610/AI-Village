import Phaser from "phaser";
import type {
  AgentSnapshot,
  DialogueMessage,
  EventMessage,
  ReflectionMessage,
  TickMessage,
} from "../types/sim";

interface AgentVisual {
  container: Phaser.GameObjects.Container;
  selectionRing: Phaser.GameObjects.Arc;
  sprite: Phaser.GameObjects.Sprite;
  nameText: Phaser.GameObjects.Text;
  lastX: number;
  lastY: number;
}

interface ActiveBubble {
  speakerId: string;
  container: Phaser.GameObjects.Container;
  expiryTimer: Phaser.Time.TimerEvent;
}

const DEFAULT_TILE_SIZE = 32;
const MIN_ZOOM = 0.5;
const MAX_ZOOM = 2.5;
const FRAMES_PER_AGENT = 4;
const BUBBLE_DEPTH = 60;
const BUBBLE_OFFSET_Y = 40;
const BUBBLE_DURATION_MS = 2400;
const TURN_STAGGER_MS = 1800;
const MAX_DIALOGUE_TURNS = 6;
const MAX_BUBBLE_CHARS = 160;
const EVENT_RING_DEPTH = 55;
const EVENT_BANNER_DEPTH = 65;
const EVENT_DURATION_MS = 2600;
const REFLECTION_DURATION_MS = 2400;
const DRAG_THRESHOLD_PX = 5;

interface TransientCueOptions {
  x: number;
  y: number;
  fillColor: number;
  strokeColor: number;
  maxScale: number;
  durationMs: number;
  text: string;
  textColor: string;
  backgroundColor: string;
  bannerLiftPx: number;
  wordWrapWidth: number;
}

function isTextInputFocused(): boolean {
  const active = document.activeElement;
  return (
    active instanceof HTMLInputElement ||
    active instanceof HTMLTextAreaElement ||
    active instanceof HTMLSelectElement ||
    (active instanceof HTMLElement && active.isContentEditable)
  );
}

/** Phaser 3 scene rendering the Tiled village map, location labels, and server-synced agents. */
export class VillageScene extends Phaser.Scene {
  private isReady = false;
  private pendingTick: TickMessage | null = null;
  private collisionLayer: Phaser.Tilemaps.TilemapLayer | null = null;
  private readonly agentVisuals = new Map<string, AgentVisual>();
  private readonly locationCenters = new Map<string, { x: number; y: number }>();
  private readonly activeBubbles = new Map<string, ActiveBubble>();
  private readonly dialogueTimers = new Set<Phaser.Time.TimerEvent>();
  private readonly speakerDialogueSeq = new Map<string, number>();
  private readonly transientEventObjects = new Set<Phaser.GameObjects.GameObject>();
  private dialogueSeqCounter = 0;
  private tileSize = DEFAULT_TILE_SIZE;

  private isDragging = false;
  private hasPanned = false;
  private dragStartX = 0;
  private dragStartY = 0;
  private camStartScrollX = 0;
  private camStartScrollY = 0;
  private selectedAgentId: string | null = null;
  private onAgentSelect: ((agentId: string) => void) | null = null;

  constructor() {
    super({ key: "VillageScene" });
  }

  public preload(): void {
    this.load.tilemapTiledJSON("village-map", "/assets/map.json");
    this.load.image("tileset", "/assets/tileset.png");
    this.load.spritesheet("villagers", "/assets/sprites.png", {
      frameWidth: DEFAULT_TILE_SIZE,
      frameHeight: DEFAULT_TILE_SIZE,
    });
  }

  public create(): void {
    const map = this.make.tilemap({ key: "village-map" });
    this.tileSize = map.tileWidth || DEFAULT_TILE_SIZE;

    const tileset = map.addTilesetImage("village_tiles", "tileset");
    if (tileset === null) {
      throw new Error("Unable to bind Tiled tileset 'village_tiles' to texture 'tileset'");
    }

    const groundLayer = map.createLayer("ground", tileset, 0, 0);
    groundLayer?.setDepth(0);

    const structuresLayer = map.createLayer("structures", tileset, 0, 0);
    structuresLayer?.setDepth(1);

    this.collisionLayer = map.createLayer("collision", tileset, 0, 0);
    this.collisionLayer?.setVisible(false).setAlpha(0.55).setDepth(5);

    this.input.keyboard?.on("keydown-C", () => {
      if (isTextInputFocused()) {
        return;
      }
      if (this.collisionLayer !== null) {
        this.collisionLayer.setVisible(!this.collisionLayer.visible);
      }
    });

    this.events.once(Phaser.Scenes.Events.SHUTDOWN, () => {
      this.cleanupTransientVisuals();
      this.isReady = false;
    });

    this.renderLocationLabels(map);
    this.configureCamera(map);

    this.isReady = true;
    if (this.pendingTick !== null) {
      const latest = this.pendingTick;
      this.pendingTick = null;
      this.applyTick(latest);
    }
  }

  /** Enable or suspend Phaser keyboard handling while DOM form inputs hold focus. */
  public setKeyboardEnabled(enabled: boolean): void {
    if (this.input.keyboard !== null) {
      this.input.keyboard.enabled = enabled;
    }
  }

  /** Register a callback invoked when an agent sprite is clicked without dragging. */
  public setOnAgentSelect(callback: ((agentId: string) => void) | null): void {
    this.onAgentSelect = callback;
  }

  /** Highlight the currently selected agent on the map or clear selection when null. */
  public setSelectedAgent(agentId: string | null): void {
    this.selectedAgentId = agentId;
    for (const [id, visual] of this.agentVisuals.entries()) {
      visual.selectionRing.setVisible(id === agentId);
    }
  }

  public override update(): void {
    if (!this.isReady) {
      return;
    }
    for (const [speakerId, bubble] of this.activeBubbles.entries()) {
      const visual = this.agentVisuals.get(speakerId);
      if (visual !== undefined) {
        bubble.container.setPosition(
          visual.container.x,
          visual.container.y - BUBBLE_OFFSET_Y,
        );
      }
    }
  }

  /** Apply an authoritative server tick snapshot to agent visuals without client pathfinding. */
  public applyTick(tickMsg: TickMessage): void {
    if (!this.isReady) {
      this.pendingTick = tickMsg;
      return;
    }

    const safeSpeed = tickMsg.speed > 0 ? tickMsg.speed : 1;
    const tweenDuration = Math.min(450, Math.max(45, (1000 / safeSpeed) * 0.8));

    for (const agent of tickMsg.agents) {
      this.syncAgentVisual(agent, tickMsg.tick, tweenDuration);
    }
  }

  /** Sequence live dialogue turns into depth >= 60 speech bubbles tracking their speakers. */
  public showDialogue(msg: DialogueMessage): void {
    if (!this.isReady || msg.turns.length === 0) {
      return;
    }

    const turns = msg.turns.slice(0, MAX_DIALOGUE_TURNS);
    this.dialogueSeqCounter += 1;
    const seq = this.dialogueSeqCounter;

    for (const participantId of msg.participants) {
      this.speakerDialogueSeq.set(participantId, seq);
    }
    for (const turn of turns) {
      this.speakerDialogueSeq.set(turn.speaker_id, seq);
    }

    turns.forEach((turn, idx) => {
      const delayMs = idx * TURN_STAGGER_MS;
      if (delayMs === 0) {
        this.renderSpeakerBubble(turn.speaker_id, turn.speaker_name, turn.text);
        return;
      }

      const timer = this.time.delayedCall(delayMs, () => {
        this.dialogueTimers.delete(timer);
        if (!this.isReady) {
          return;
        }
        if (this.speakerDialogueSeq.get(turn.speaker_id) !== seq) {
          return;
        }
        this.renderSpeakerBubble(turn.speaker_id, turn.speaker_name, turn.text);
      });
      this.dialogueTimers.add(timer);
    });
  }

  /** Display a transient location pulse ring and banner when a god-mode event occurs. */
  public showEvent(msg: EventMessage): void {
    if (!this.isReady) {
      return;
    }

    const target = this.resolveEventTarget(msg.location);
    const rawText = msg.text.trim();
    const truncated =
      rawText.length > 96 ? `${rawText.slice(0, 93).trimEnd()}...` : rawText;
    const prefix = msg.location ? `[${msg.location}] ` : "[Village Event] ";

    this.spawnTransientCue({
      x: target.x,
      y: target.y,
      fillColor: 0xf59e0b,
      strokeColor: 0xfbbf24,
      maxScale: 4.5,
      durationMs: EVENT_DURATION_MS,
      text: `${prefix}${truncated}`,
      textColor: "#fef3c7",
      backgroundColor: "rgba(120, 53, 15, 0.92)",
      bannerLiftPx: 28,
      wordWrapWidth: 260,
    });
  }

  /** Display a transient violet halo and badge when an agent synthesizes a reflection. */
  public showReflection(msg: ReflectionMessage): void {
    if (!this.isReady) {
      return;
    }

    const visual = this.agentVisuals.get(msg.agent_id);
    const target = visual
      ? { x: visual.container.x, y: visual.container.y }
      : { x: this.cameras.main.midPoint.x, y: this.cameras.main.midPoint.y };

    this.spawnTransientCue({
      x: target.x,
      y: target.y,
      fillColor: 0xa855f7,
      strokeColor: 0xc084fc,
      maxScale: 3.2,
      durationMs: REFLECTION_DURATION_MS,
      text: `${msg.agent_name} reflected`,
      textColor: "#f3e8ff",
      backgroundColor: "rgba(88, 28, 135, 0.92)",
      bannerLiftPx: 22,
      wordWrapWidth: 220,
    });
  }

  private spawnTransientCue(options: TransientCueOptions): void {
    const ring: Phaser.GameObjects.Arc = this.add
      .circle(options.x, options.y, 16, options.fillColor, 0.2)
      .setStrokeStyle(3, options.strokeColor, 0.95)
      .setDepth(EVENT_RING_DEPTH);
    this.transientEventObjects.add(ring);

    this.tweens.add({
      targets: ring,
      scale: { from: 0.75, to: options.maxScale },
      alpha: { from: 0.95, to: 0 },
      duration: options.durationMs,
      ease: "Cubic.easeOut",
      onComplete: () => {
        this.transientEventObjects.delete(ring);
        ring.destroy();
      },
    });

    const banner = this.add
      .text(options.x, options.y - 28, options.text, {
        fontFamily: "Inter, system-ui, sans-serif",
        fontSize: "12px",
        fontStyle: "bold",
        color: options.textColor,
        backgroundColor: options.backgroundColor,
        padding: { left: 8, right: 8, top: 5, bottom: 5 },
        wordWrap: { width: options.wordWrapWidth, useAdvancedWrap: true },
        align: "center",
      })
      .setOrigin(0.5, 1)
      .setDepth(EVENT_BANNER_DEPTH);
    banner.setResolution(2);
    this.transientEventObjects.add(banner);

    this.tweens.add({
      targets: banner,
      y: options.y - 28 - options.bannerLiftPx,
      duration: options.durationMs,
      ease: "Sine.easeOut",
    });

    this.tweens.add({
      targets: banner,
      alpha: 0,
      delay: Math.floor(options.durationMs * 0.6),
      duration: Math.ceil(options.durationMs * 0.4),
      ease: "Quad.easeIn",
      onComplete: () => {
        this.transientEventObjects.delete(banner);
        banner.destroy();
      },
    });
  }

  private renderSpeakerBubble(
    speakerId: string,
    speakerName: string,
    text: string,
  ): void {
    this.clearSpeakerBubble(speakerId);

    const visual = this.agentVisuals.get(speakerId);
    const cleanText = text.trim();
    if (visual === undefined || cleanText.length === 0) {
      return;
    }

    const displayText =
      cleanText.length > MAX_BUBBLE_CHARS
        ? `${cleanText.slice(0, MAX_BUBBLE_CHARS - 3).trimEnd()}...`
        : cleanText;

    const bubbleText = this.add
      .text(0, 0, `${speakerName}: ${displayText}`, {
        fontFamily: "Inter, system-ui, sans-serif",
        fontSize: "11px",
        fontStyle: "normal",
        color: "#f8fafc",
        wordWrap: { width: 190, useAdvancedWrap: true },
        lineSpacing: 2,
      })
      .setOrigin(0.5, 1);
    bubbleText.setResolution(2);

    const padX = 8;
    const padY = 6;
    const pointerHeight = 6;
    const boxWidth = Math.max(64, Math.ceil(bubbleText.width) + padX * 2);
    const boxHeight = Math.ceil(bubbleText.height) + padY * 2;
    const topY = -(boxHeight + pointerHeight);

    const bg = this.add.graphics();
    bg.fillStyle(0x0f172a, 0.94);
    bg.lineStyle(1.5, 0x38bdf8, 0.95);
    bg.fillRoundedRect(-boxWidth / 2, topY, boxWidth, boxHeight, 8);
    bg.strokeRoundedRect(-boxWidth / 2, topY, boxWidth, boxHeight, 8);
    bg.fillTriangle(-5, -pointerHeight, 5, -pointerHeight, 0, 0);
    bg.beginPath();
    bg.moveTo(-5, -pointerHeight);
    bg.lineTo(0, 0);
    bg.lineTo(5, -pointerHeight);
    bg.strokePath();

    bubbleText.setPosition(0, -(pointerHeight + padY));

    const container = this.add
      .container(
        visual.container.x,
        visual.container.y - BUBBLE_OFFSET_Y,
        [bg, bubbleText],
      )
      .setDepth(BUBBLE_DEPTH)
      .setAlpha(0);

    this.tweens.add({
      targets: container,
      alpha: 1,
      duration: 120,
      ease: "Sine.easeOut",
    });

    const expiryTimer = this.time.delayedCall(BUBBLE_DURATION_MS, () => {
      this.clearSpeakerBubble(speakerId);
    });

    this.activeBubbles.set(speakerId, {
      speakerId,
      container,
      expiryTimer,
    });
  }

  private clearSpeakerBubble(speakerId: string): void {
    const existing = this.activeBubbles.get(speakerId);
    if (existing === undefined) {
      return;
    }
    this.activeBubbles.delete(speakerId);
    existing.expiryTimer.remove(false);
    this.tweens.killTweensOf(existing.container);
    existing.container.destroy(true);
  }

  private resolveEventTarget(location: string | null): { x: number; y: number } {
    if (location !== null) {
      const exact = this.locationCenters.get(location);
      if (exact !== undefined) {
        return exact;
      }
      const lower = location.trim().toLowerCase();
      for (const [name, coords] of this.locationCenters.entries()) {
        if (name.toLowerCase() === lower) {
          return coords;
        }
      }
    }
    return {
      x: this.cameras.main.midPoint.x,
      y: this.cameras.main.midPoint.y,
    };
  }

  private cleanupTransientVisuals(): void {
    for (const timer of this.dialogueTimers) {
      timer.remove(false);
    }
    this.dialogueTimers.clear();

    for (const speakerId of Array.from(this.activeBubbles.keys())) {
      this.clearSpeakerBubble(speakerId);
    }

    for (const obj of this.transientEventObjects) {
      this.tweens.killTweensOf(obj);
      obj.destroy();
    }
    this.transientEventObjects.clear();
  }

  private renderLocationLabels(map: Phaser.Tilemaps.Tilemap): void {
    this.locationCenters.clear();
    const locationObjects = map.getObjectLayer("locations")?.objects ?? [];
    for (const obj of locationObjects) {
      if (!obj.name) {
        continue;
      }
      const centerX = (obj.x ?? 0) + (obj.width ?? 0) / 2;
      const centerY = (obj.y ?? 0) + (obj.height ?? 0) / 2;
      this.locationCenters.set(obj.name, { x: centerX, y: centerY });

      const label = this.add
        .text(centerX, centerY, obj.name, {
          fontFamily: "Inter, system-ui, sans-serif",
          fontSize: "12px",
          fontStyle: "bold",
          color: "#f8fafc",
          backgroundColor: "rgba(15, 23, 42, 0.76)",
          padding: { left: 6, right: 6, top: 3, bottom: 3 },
        })
        .setOrigin(0.5)
        .setDepth(20);
      label.setResolution(2);
    }
  }

  private configureCamera(map: Phaser.Tilemaps.Tilemap): void {
    const cam = this.cameras.main;
    cam.setBounds(0, 0, map.widthInPixels, map.heightInPixels);
    cam.setBackgroundColor("#0f172a");

    const fitZoom = Math.min(
      this.scale.width / map.widthInPixels,
      this.scale.height / map.heightInPixels,
      1.2,
    );
    cam.setZoom(Phaser.Math.Clamp(fitZoom, MIN_ZOOM, MAX_ZOOM));
    cam.centerOn(map.widthInPixels / 2, map.heightInPixels / 2);

    this.scale.on("resize", (gameSize: Phaser.Structs.Size) => {
      cam.setSize(gameSize.width, gameSize.height);
    });

    this.input.on("pointerdown", (pointer: Phaser.Input.Pointer) => {
      if (pointer.leftButtonDown() || pointer.middleButtonDown()) {
        this.isDragging = true;
        this.hasPanned = false;
        this.dragStartX = pointer.x;
        this.dragStartY = pointer.y;
        this.camStartScrollX = cam.scrollX;
        this.camStartScrollY = cam.scrollY;
      }
    });

    this.input.on("pointermove", (pointer: Phaser.Input.Pointer) => {
      if (!this.isDragging) {
        return;
      }
      if (!pointer.leftButtonDown() && !pointer.middleButtonDown()) {
        this.isDragging = false;
        return;
      }
      if (
        Math.hypot(pointer.x - this.dragStartX, pointer.y - this.dragStartY) >
        DRAG_THRESHOLD_PX
      ) {
        this.hasPanned = true;
      }
      const dx = (pointer.x - this.dragStartX) / cam.zoom;
      const dy = (pointer.y - this.dragStartY) / cam.zoom;
      cam.scrollX = this.camStartScrollX - dx;
      cam.scrollY = this.camStartScrollY - dy;
    });

    this.input.on("pointerup", () => {
      this.isDragging = false;
    });

    this.input.on(
      "wheel",
      (
        _pointer: Phaser.Input.Pointer,
        _currentlyOver: Phaser.GameObjects.GameObject[],
        _deltaX: number,
        deltaY: number,
      ) => {
        const zoomFactor = deltaY > 0 ? 0.9 : 1.1;
        cam.setZoom(Phaser.Math.Clamp(cam.zoom * zoomFactor, MIN_ZOOM, MAX_ZOOM));
      },
    );
  }

  private syncAgentVisual(
    agent: AgentSnapshot,
    tick: number,
    tweenDuration: number,
  ): void {
    const halfTile = this.tileSize / 2;
    const targetPx = agent.x * this.tileSize + halfTile;
    const targetPy = agent.y * this.tileSize + halfTile;
    const totalFrames = this.textures.get("villagers").getFrameNames().length;
    const rowCount = Math.max(1, Math.floor(totalFrames / FRAMES_PER_AGENT));
    const safeRow = Math.max(0, agent.sprite_index) % rowCount;
    const baseFrame = safeRow * FRAMES_PER_AGENT;

    const existing = this.agentVisuals.get(agent.id);
    if (existing === undefined) {
      const selectionRing = this.add
        .circle(0, 8, 16, 0x38bdf8, 0.14)
        .setStrokeStyle(2, 0x38bdf8, 0.95)
        .setVisible(agent.id === this.selectedAgentId);

      const sprite = this.add
        .sprite(0, 0, "villagers", baseFrame)
        .setInteractive({ useHandCursor: true });
      sprite.on("pointerup", (pointer: Phaser.Input.Pointer) => {
        if (
          !this.hasPanned &&
          Math.hypot(pointer.x - this.dragStartX, pointer.y - this.dragStartY) <=
            DRAG_THRESHOLD_PX &&
          pointer.button === 0
        ) {
          this.onAgentSelect?.(agent.id);
        }
      });

      const nameText = this.add
        .text(0, -20, agent.name, {
          fontFamily: "Inter, system-ui, sans-serif",
          fontSize: "11px",
          fontStyle: "bold",
          color: "#f8fafc",
          backgroundColor: "rgba(15, 23, 42, 0.8)",
          padding: { left: 4, right: 4, top: 1, bottom: 1 },
        })
        .setOrigin(0.5, 1);
      nameText.setResolution(2);

      const container = this.add
        .container(targetPx, targetPy, [selectionRing, sprite, nameText])
        .setDepth(10 + agent.y);

      this.agentVisuals.set(agent.id, {
        container,
        selectionRing,
        sprite,
        nameText,
        lastX: agent.x,
        lastY: agent.y,
      });
      return;
    }

    if (agent.x !== existing.lastX || agent.y !== existing.lastY) {
      this.tweens.killTweensOf(existing.container);
      const walkFrame = baseFrame + (tick % FRAMES_PER_AGENT);
      existing.sprite.setFrame(walkFrame);
      existing.container.setDepth(10 + agent.y);

      this.tweens.add({
        targets: existing.container,
        x: targetPx,
        y: targetPy,
        duration: tweenDuration,
        ease: "Linear",
      });

      existing.lastX = agent.x;
      existing.lastY = agent.y;
    } else {
      existing.sprite.setFrame(baseFrame);
      existing.container.setDepth(10 + agent.y);
    }
  }
}
