import { useEffect, useRef, useState } from "react";
import Viewer from "bpmn-js/lib/NavigatedViewer";
import { Maximize, Minus, Plus } from "lucide-react";
import "bpmn-js/dist/assets/diagram-js.css";
import "bpmn-js/dist/assets/bpmn-font/css/bpmn.css";

export function Diagram({
  xml,
  selected,
  highlighted,
  onSelect,
}: {
  xml: string;
  selected: string | null;
  highlighted: string[];
  onSelect: (id: string) => void;
}) {
  const element = useRef<HTMLDivElement>(null);
  const viewer = useRef<Viewer | null>(null);
  const select = useRef(onSelect);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  select.current = onSelect;
  useEffect(() => {
    const container = element.current;
    if (!container) return;
    const instance = new Viewer({ container });
    viewer.current = instance;
    instance
      .get("eventBus")
      .on("element.click", (e) => select.current(e.element.id));
    let active = true;
    let imported = false;
    setLoading(true);
    setError("");
    instance
      .importXML(xml)
      .then(() => {
        if (active) {
          imported = true;
          instance.get("canvas").zoom("fit-viewport", "auto");
          setLoading(false);
          setRevision((v) => v + 1);
        }
      })
      .catch(() => {
        if (active) {
          setError(
            "The BPMN renderer could not display this diagram. Inspect or correct its BPMNDI coordinates in the XML editor.",
          );
          setLoading(false);
        }
      });
    const observer = new ResizeObserver(() => {
      if (active && imported)
        instance.get("canvas").zoom("fit-viewport", "auto");
    });
    observer.observe(container);
    return () => {
      active = false;
      observer.disconnect();
      instance.destroy();
      viewer.current = null;
    };
    // A fresh viewer imports each immutable model version.
  }, [xml]);
  useEffect(() => {
    if (!revision) return;
    const canvas = viewer.current?.get("canvas");
    if (!canvas) return;
    const ids = [...highlighted, ...(selected ? [selected] : [])];
    ids.forEach((id) => {
      try {
        canvas.addMarker(
          id,
          id === selected ? "studio-selected" : "studio-trace",
        );
      } catch {
        /* diagram may omit annotations */
      }
    });
    return () =>
      ids.forEach((id) => {
        try {
          canvas.removeMarker(id, "studio-selected");
          canvas.removeMarker(id, "studio-trace");
        } catch {
          /* viewer was replaced */
        }
      });
  }, [selected, highlighted, revision]);
  return (
    <div className="diagram-shell">
      <div className="diagram-meta">
        <span className="eyebrow">BPMN 2.0 / PROCESS VIEW</span>
        <span>Drag to pan · scroll to zoom · select a task</span>
      </div>
      <section
        className="diagram"
        ref={element}
        aria-label="Interactive BPMN process diagram"
      />
      {loading && (
        <div className="canvas-notice" role="status">
          Rendering process…
        </div>
      )}
      {error && (
        <div className="canvas-notice error" role="alert">
          {error}
        </div>
      )}
      <div className="canvas-tools">
        <button
          type="button"
          aria-label="Zoom out"
          onClick={() => {
            const c = viewer.current?.get("canvas");
            if (c) c.zoom(c.zoom() / 1.25);
          }}
        >
          <Minus size={16} />
        </button>
        <button
          type="button"
          aria-label="Fit diagram"
          onClick={() =>
            viewer.current?.get("canvas").zoom("fit-viewport", "auto")
          }
        >
          <Maximize size={16} />
        </button>
        <button
          type="button"
          aria-label="Zoom in"
          onClick={() => {
            const c = viewer.current?.get("canvas");
            if (c) c.zoom(c.zoom() * 1.25);
          }}
        >
          <Plus size={16} />
        </button>
      </div>
    </div>
  );
}
