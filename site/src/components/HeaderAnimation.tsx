import { useEffect, useRef } from 'react';

interface WaveLayer {
  color: string;
  amplitude: number;
  cycles: number;
  speed: number;
  baseline: number;
}

// Stacked bands echoing the Lakebase brand icon: light pinks on top,
// down to the lava red wave at the bottom.
const LAYERS: WaveLayer[] = [
  { color: '#FFD0CB', amplitude: 22, cycles: 1.4, speed: 0.16, baseline: 0.5 },
  { color: '#FFAFA5', amplitude: 26, cycles: 1.1, speed: 0.22, baseline: 0.61 },
  { color: '#FF8576', amplitude: 24, cycles: 1.7, speed: 0.28, baseline: 0.71 },
  { color: '#FF5C4C', amplitude: 28, cycles: 1.3, speed: 0.2, baseline: 0.81 },
  { color: '#FF3621', amplitude: 30, cycles: 1.0, speed: 0.26, baseline: 0.91 },
];

export default function HeaderAnimation() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
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
    window.addEventListener('resize', updateCanvasSize);

    const backgroundColor = '#FFFFFF';
    const separatorColor = '#FFFFFF';

    const prefersReducedMotion = window.matchMedia(
      '(prefers-reduced-motion: reduce)',
    ).matches;

    const step = 6;
    let animationFrame = 0;
    let start: number | null = null;

    const drawFrame = (elapsedSeconds: number) => {
      ctx.fillStyle = backgroundColor;
      ctx.fillRect(0, 0, width, height);

      const scale = Math.max(0.65, Math.min(height / 720, 1.6));

      LAYERS.forEach((layer) => {
        const baseY = height * layer.baseline;
        const amp = layer.amplitude * scale;
        const phase = elapsedSeconds * layer.speed;

        const yAt = (x: number) =>
          baseY +
          Math.sin((x / width) * layer.cycles * Math.PI * 2 + phase) * amp;

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
      window.removeEventListener('resize', updateCanvasSize);
      if (animationFrame) cancelAnimationFrame(animationFrame);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      style={{
        position: 'absolute',
        inset: 0,
        width: '100%',
        height: '100%',
      }}
    />
  );
}
