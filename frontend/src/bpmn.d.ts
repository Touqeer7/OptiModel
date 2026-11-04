declare module "bpmn-js/lib/NavigatedViewer" {
  export default class Viewer {
    constructor(options: { container: HTMLElement });
    importXML(xml: string): Promise<{ warnings: unknown[] }>;
    get(name: "canvas"): {
      zoom(value?: string | number, center?: string): number;
      addMarker(id: string, marker: string): void;
      removeMarker(id: string, marker: string): void;
      scrollToElement(id: string): void;
    };
    get(name: "eventBus"): {
      on(event: string, fn: (event: { element: { id: string } }) => void): void;
    };
    destroy(): void;
  }
}
