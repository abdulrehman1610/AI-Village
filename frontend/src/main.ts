import Phaser from "phaser";

class BootScene extends Phaser.Scene {
  constructor() {
    super({ key: "BootScene" });
  }

  create(): void {
    const { width, height } = this.scale;
    this.add
      .text(width / 2, height / 2, "AI Village initializing...", {
        fontFamily: "Inter, system-ui, sans-serif",
        fontSize: "20px",
        color: "#e2e8f0",
      })
      .setOrigin(0.5);
  }
}

const config: Phaser.Types.Core.GameConfig = {
  type: Phaser.AUTO,
  parent: "game-container",
  width: 960,
  height: 640,
  backgroundColor: "#0f172a",
  pixelArt: true,
  scale: {
    mode: Phaser.Scale.FIT,
    autoCenter: Phaser.Scale.CENTER_BOTH,
  },
  scene: [BootScene],
};

new Phaser.Game(config);
