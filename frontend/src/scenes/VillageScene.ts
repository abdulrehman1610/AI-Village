import Phaser from "phaser";
import type { AgentSnapshot, TickMessage } from "../types/sim";

interface AgentVisual {
  container: Phaser.GameObjects.Container;
  sprite: Phaser.GameObjects.Sprite;
  nameText: Phaser.GameObjects.Text;
  lastX: number;
  lastY: number;
}

const DEFAULT_TILE_SIZE = 32;
const MIN_ZOOM = 0.5;
const MAX_ZOOM = 2.5;
const FRAMES_PER_AGENT = 4;

/** Phaser 3 scene rendering the Tiled village map, location labels, and server-synced agents. */
export class VillageScene extends Phaser.Scene {
  private isReady = false;
  private pendingTick: TickMessage | null = null;
  private collisionLayer: Phaser.Tilemaps.TilemapLayer | null = null;
  private readonly agentVisuals = new Map<string, AgentVisual>();
  private tileSize = DEFAULT_TILE_SIZE;

  private isDragging = false;
  private dragStartX = 0;
  private dragStartY = 0;
  private camStartScrollX = 0;
  private camStartScrollY = 0;

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
      if (this.collisionLayer !== null) {
        this.collisionLayer.setVisible(!this.collisionLayer.visible);
      }
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

  private renderLocationLabels(map: Phaser.Tilemaps.Tilemap): void {
    const locationObjects = map.getObjectLayer("locations")?.objects ?? [];
    for (const obj of locationObjects) {
      if (!obj.name) {
        continue;
      }
      const centerX = (obj.x ?? 0) + (obj.width ?? 0) / 2;
      const centerY = (obj.y ?? 0) + (obj.height ?? 0) / 2;

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
    const baseFrame = Math.max(0, agent.sprite_index) * FRAMES_PER_AGENT;

    const existing = this.agentVisuals.get(agent.id);
    if (existing === undefined) {
      const sprite = this.add.sprite(0, 0, "villagers", baseFrame);
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
        .container(targetPx, targetPy, [sprite, nameText])
        .setDepth(10 + agent.y);

      this.agentVisuals.set(agent.id, {
        container,
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
