import { BarChart, HeatmapChart, LineChart } from "echarts/charts";
import { AriaComponent, GridComponent, LegendComponent, TooltipComponent, VisualMapComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer, SVGRenderer } from "echarts/renderers";

/** ECharts with only the parts RawiBumi uses (tree-shaken), for the screen and the report. */
echarts.use([BarChart, HeatmapChart, LineChart, AriaComponent, GridComponent, LegendComponent, TooltipComponent, VisualMapComponent, CanvasRenderer, SVGRenderer]);

export { echarts };

/** A chart as an SVG string (server-side mode), for the HTML report. */
export function optionToSvg(option: echarts.EChartsCoreOption, width: number, height: number): string {
  const chart = echarts.init(null, null, { renderer: "svg", ssr: true, width, height });
  try {
    chart.setOption(option);
    return chart.renderToSVGString();
  } finally {
    chart.dispose();
  }
}
