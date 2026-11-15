import { useLayoutEffect, useRef, useState, type PointerEvent } from "react";
import {
  describeMetric,
  formatTick,
  formatValue,
  niceTicks,
  type MetricSeries,
} from "../device/telemetry";

interface Props {
  series: MetricSeries;
  /** Shared time domain so every small multiple lines up. */
  domain: [number, number];
}

const HEIGHT = 132;
const PAD = { top: 10, right: 12, bottom: 22, left: 48 };

const timeFmt = new Intl.DateTimeFormat(undefined, {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

/** One reading over time: a 2px line (a step line for on/off readings) with a crosshair. */
export function MetricChart({ series, domain }: Props) {
  const wrap = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(320);
  const [hover, setHover] = useState<number>();
  const { label, unit } = describeMetric(series.name);

  useLayoutEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const update = () => setWidth(Math.max(200, el.clientWidth));
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const points = series.points;
  const isBool = series.kind === "boolean";
  const [t0, t1] = domain[0] === domain[1] ? [domain[0] - 1000, domain[1]] : domain;
  let vMin = isBool ? 0 : Math.min(...points.map((p) => p.v));
  let vMax = isBool ? 1 : Math.max(...points.map((p) => p.v));
  if (!isBool) {
    if (vMin === vMax) {
      vMin -= 1;
      vMax += 1;
    }
    const ticks = niceTicks(vMin, vMax, 4);
    vMin = Math.min(vMin, ticks[0]);
    vMax = Math.max(vMax, ticks[ticks.length - 1]);
  }
  const yTicks = isBool ? [0, 1] : niceTicks(vMin, vMax, 4);
  const innerW = width - PAD.left - PAD.right;
  const innerH = HEIGHT - PAD.top - PAD.bottom;
  const x = (t: number) => PAD.left + ((t - t0) / (t1 - t0)) * innerW;
  const y = (v: number) => PAD.top + (1 - (v - vMin) / (vMax - vMin || 1)) * innerH;

  let path = "";
  points.forEach((p, i) => {
    const px = x(p.t).toFixed(1);
    const py = y(p.v).toFixed(1);
    if (i === 0) path += `M${px},${py}`;
    else if (isBool) path += `H${px}V${py}`;
    else path += `L${px},${py}`;
  });

  const xTicks = [t0, (t0 + t1) / 2, t1];
  const hovered = hover === undefined ? undefined : points[hover];
  const last = points.at(-1);

  function onMove(e: PointerEvent<SVGRectElement>) {
    if (points.length === 0) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const t = t0 + ((e.clientX - rect.left) / rect.width) * (t1 - t0);
    let best = 0;
    for (let i = 1; i < points.length; i++) {
      if (Math.abs(points[i].t - t) < Math.abs(points[best].t - t)) best = i;
    }
    setHover(best);
  }

  const latestText = formatValue(series.latest, isBool ? "" : unit);
  return (
    <figure className="metric">
      <figcaption>
        <span className="metric-label">
          {label}
          {unit && !isBool ? <span className="metric-unit"> ({unit})</span> : null}
        </span>
        <span className="metric-value">{latestText}</span>
      </figcaption>
      <div ref={wrap} className="metric-plot">
        <svg
          width={width}
          height={HEIGHT}
          role="img"
          aria-label={`${label}: latest ${latestText}, ${points.length} samples`}
        >
          {yTicks.map((v) => (
            <g key={v}>
              <line className="grid" x1={PAD.left} x2={width - PAD.right} y1={y(v)} y2={y(v)} />
              <text className="tick" x={PAD.left - 6} y={y(v)} dy="0.32em" textAnchor="end">
                {isBool ? (v ? "On" : "Off") : formatTick(v)}
              </text>
            </g>
          ))}
          {xTicks.map((t, i) => (
            <text
              key={i}
              className="tick"
              x={x(t)}
              y={HEIGHT - 6}
              textAnchor={i === 0 ? "start" : i === 2 ? "end" : "middle"}
            >
              {timeFmt.format(t)}
            </text>
          ))}
          <path className="series-line" d={path} />
          {last && <circle className="series-dot" cx={x(last.t)} cy={y(last.v)} r={4} />}
          {hovered && (
            <g>
              <line
                className="crosshair"
                x1={x(hovered.t)}
                x2={x(hovered.t)}
                y1={PAD.top}
                y2={PAD.top + innerH}
              />
              <circle className="series-dot" cx={x(hovered.t)} cy={y(hovered.v)} r={4} />
            </g>
          )}
          <rect
            className="hit"
            x={PAD.left}
            y={PAD.top}
            width={innerW}
            height={innerH}
            onPointerMove={onMove}
            onPointerLeave={() => setHover(undefined)}
          />
        </svg>
        {hovered && (
          <div
            className="tooltip"
            style={
              // Beside the crosshair, on the side with more room, so it never hides the value.
              x(hovered.t) < width / 2
                ? { left: x(hovered.t) + 8, top: PAD.top }
                : { right: width - x(hovered.t) + 8, top: PAD.top }
            }
          >
            <strong>{formatValue(isBool ? hovered.v === 1 : hovered.v, isBool ? "" : unit)}</strong>
            <span>{timeFmt.format(hovered.t)}</span>
          </div>
        )}
      </div>
    </figure>
  );
}
