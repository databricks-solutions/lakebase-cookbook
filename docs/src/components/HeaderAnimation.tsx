import React, { useEffect, useRef } from "react";

interface HeaderAnimationProps {
  isDarkMode: boolean;
}

interface WaveLayer {
  color: string; // fill color (Lakebase lava palette, light -> dark)
  amplitude: number; // wave height in px (before viewport scaling)
  cycles: number; // number of wave cycles across the full width
  speed: number; // horizontal roll speed in radians/second
  baseline: number; // resting line as a fraction of canvas height
}

// Stacked bands echoing the Lakebase brand icon: light pinks on top,
// down to the lava red wave at the bottom.
const LAYERS: WaveLayer[] = [
  { color: "#FFD0CB", amplitude: 22, cycles: 1.4, speed: 0.16, baseline: 0.5 },
  { color: "#FFAFA5", amplitude: 26, cycles: 1.1, speed: 0.22, baseline: 0.61 },
  { color: "#FF8576", amplitude: 24, cycles: 1.7, speed: 0.28, baseline: 0.71 },
  { color: "#FF5C4C", amplitude: 28, cycles: 1.3, speed: 0.2, baseline: 0.81 },
  { color: "#FF3621", amplitude: 30, cycles: 1.0, speed: 0.26, baseline: 0.91 },
];

const HeaderAnimation: React.FC<HeaderAnimationProps> = ({ isDarkMode }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let width = 0;
    let height = 0;

    const updateCanvasSize = () => {
      const dpr = window.devicePixelRatio || 1;
      const rect = canvas.getBoundingClientRect();
      width = rect.width;
      height = rect.height;
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      canvas.width = width * dpr;
      canvas.height = height * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    updateCanvasSize();
    window.addEventListener("resize", updateCanvasSize);

    const backgroundColor = isDarkMode ? "#0B2026" : "#EEEDE9";
    // White separators in light mode; the dark navy background in dark mode,
    // so the bands read as distinct waves in both themes.
    const separatorColor = isDarkMode ? "#0B2026" : "#FFFFFF";

    const prefersReducedMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;

    const step = 6;
    let animationFrame: number;
    let start: number | null = null;

    const drawFrame = (elapsedSeconds: number) => {
      ctx.fillStyle = backgroundColor;
      ctx.fillRect(0, 0, width, height);

      // Scale wave height to the viewport so it feels consistent at any size.
      const scale = Math.max(0.65, Math.min(height / 720, 1.6));

      LAYERS.forEach((layer) => {
        const baseY = height * layer.baseline;
        const amp = layer.amplitude * scale;
        const phase = elapsedSeconds * layer.speed;

        const yAt = (x: number) =>
          baseY + Math.sin((x / width) * layer.cycles * Math.PI * 2 + phase) * amp;

        // Filled wave down to the bottom edge.
        ctx.beginPath();
        ctx.moveTo(0, yAt(0));
        for (let x = step; x <= width; x += step) {
          ctx.lineTo(x, yAt(x));
        }
        ctx.lineTo(width, height);
        ctx.lineTo(0, height);
        ctx.closePath();
        ctx.fillStyle = layer.color;
        ctx.fill();

        // Brand-style separator line riding the crest of each wave.
        ctx.beginPath();
        ctx.moveTo(0, yAt(0));
        for (let x = step; x <= width; x += step) {
          ctx.lineTo(x, yAt(x));
        }
        ctx.lineWidth = Math.max(3, 6 * scale);
        ctx.strokeStyle = separatorColor;
        ctx.stroke();
      });
    };

    const animate = (timestamp: number) => {
      if (start === null) start = timestamp;
      const elapsedSeconds = (timestamp - start) / 1000;
      drawFrame(elapsedSeconds);
      animationFrame = requestAnimationFrame(animate);
    };

    if (prefersReducedMotion) {
      drawFrame(0);
    } else {
      animationFrame = requestAnimationFrame(animate);
    }

    return () => {
      window.removeEventListener("resize", updateCanvasSize);
      if (animationFrame) cancelAnimationFrame(animationFrame);
    };
  }, [isDarkMode]);

  return (
    <canvas
      ref={canvasRef}
      style={{
        position: "absolute",
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        width: "100%",
        height: "100%",
      }}
    />
  );
};

export default HeaderAnimation;
