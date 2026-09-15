/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { GraphRenderer } from "@web/views/graph/graph_renderer";
import { getCustomColor, lightenColor, darkenColor, getBorderWhite } from "@web/core/colors/colors";
import { cookie } from "@web/core/browser/cookie";
import { SEP } from "@web/views/graph/graph_model";
import { _t } from "@web/core/l10n/translation";

const NO_DATA = _t("No data");
const colorScheme = cookie.get("color_scheme");
const GRAPH_LEGEND_COLOR = getCustomColor(colorScheme, "#111827", "#ffffff");
const NO_DATA_COLOR = getCustomColor(colorScheme, "#d3d3d3", "#3C3E4B");

function shortenLabel(label) {
    const groups = label.toString().split(SEP);
    let shortLabel = groups.slice(0, 3).join(SEP);
    if (shortLabel.length > 30) {
        shortLabel = `${shortLabel.slice(0, 30)}...`;
    } else if (groups.length > 3) {
        shortLabel = `${shortLabel}${SEP}...`;
    }
    return shortLabel;
}

// Bunna Bank Official 6 Brand Colors & Harmonic Extensions
const BUNNA_GRAPH_PALETTE = [
    "#541718", // Bunna Primary Maroon (Swatch 6: C:39 M:89 Y:79 K:60 | R:84 G:24 B:24)
    "#1E2917", // Bunna Secondary Deep Pine (Swatch 5: C:73 M:56 Y:81 K:73 | R:30 G:41 B:23)
    "#425727", // Bunna Forest Olive (Swatch 1: C:70 M:44 Y:100 K:39 | R:66 G:87 B:39)
    "#C17540", // Bunna Terracotta (Swatch 3: C:20 M:60 Y:84 K:5 | R:193 G:117 B:64)
    "#726732", // Bunna Bronze Olive (Swatch 2: C:50 M:47 Y:92 K:26 | R:114 G:103 B:50)
    "#1D2B32", // Bunna Deep Slate (Swatch 4: C:83 M:67 Y:58 K:62 | R:29 G:43 B:50)
    "#742526", // Bunna Maroon Accent Light
    "#304123", // Bunna Deep Pine Accent
    "#597435", // Bunna Forest Olive Light
    "#A85E2B", // Bunna Terracotta Accent
    "#8C7F40", // Bunna Bronze Accent
    "#2E3F48", // Bunna Deep Slate Light
];

export function getBunnaGraphColor(index) {
    return BUNNA_GRAPH_PALETTE[index % BUNNA_GRAPH_PALETTE.length];
}

patch(GraphRenderer.prototype, {
    getBarChartData() {
        const { stacked } = this.model.metaData;
        const { data, lineOverlayDataset } = this.model;
        const currentColorScheme = cookie.get("color_scheme");

        for (let index = 0; index < data.datasets.length; ++index) {
            const dataset = data.datasets[index];
            const itemColor = getBunnaGraphColor(index);
            if (stacked) {
                dataset.stack = "";
            }
            dataset.backgroundColor = itemColor;
            dataset.borderRadius = 4;
        }

        if (lineOverlayDataset) {
            Object.assign(lineOverlayDataset, {
                type: "line",
                order: -1,
                tension: 0,
                fill: false,
                pointHitRadius: 20,
                pointRadius: 5,
                pointHoverRadius: 10,
                backgroundColor: getCustomColor(currentColorScheme, "#1E2917", "#e9ecef"),
                borderColor: getCustomColor(currentColorScheme, "#541718", "rgba(255,255,255,.5)"),
                borderWidth: 2,
                lineWidth: 3,
            });
            return {
                ...data,
                datasets: [...data.datasets, lineOverlayDataset],
            };
        }

        return data;
    },

    getLineChartData() {
        const { cumulated } = this.model.metaData;
        const data = this.model.data;
        const currentColorScheme = cookie.get("color_scheme");

        for (let index = 0; index < data.datasets.length; ++index) {
            const dataset = data.datasets[index];
            const itemColor = getBunnaGraphColor(index);
            dataset.backgroundColor = getCustomColor(
                currentColorScheme,
                lightenColor(itemColor, 0.5),
                darkenColor(itemColor, 0.5)
            );
            dataset.cubicInterpolationMode = "monotone";
            dataset.borderColor = itemColor;
            dataset.borderWidth = 2;
            dataset.hoverBackgroundColor = dataset.borderColor;
            dataset.pointRadius = 3;
            dataset.pointHoverRadius = 6;
            if (cumulated) {
                let accumulator = dataset.cumulatedStart;
                dataset.data = dataset.data.map((value) => {
                    accumulator += value;
                    return accumulator;
                });
            }
            if (data.labels.length === 1) {
                dataset.data.unshift(undefined);
                dataset.trueLabels.unshift(undefined);
                dataset.domains.unshift(undefined);
            }
            dataset.pointBackgroundColor = dataset.borderColor;
        }
        data.labels = data.labels.length > 1 ? data.labels : ["", ...data.labels, ""];
        return data;
    },

    getPieChartData() {
        const data = this.model.data;
        const currentColorScheme = cookie.get("color_scheme");
        const colors = data.labels.map((_, index) => getBunnaGraphColor(index));
        const borderColor = getBorderWhite(currentColorScheme);

        for (const dataset of data.datasets) {
            dataset.backgroundColor = colors;
            dataset.hoverBackgroundColor = colors;
            dataset.borderColor = borderColor;
            dataset.hoverOffset = 60;
        }

        if (data.datasets.length === 0) {
            const fakeData = new Array(data.labels.length + 1);
            fakeData[data.labels.length] = 1;
            const fakeTrueLabels = new Array(data.labels.length + 1);
            fakeTrueLabels[data.labels.length] = NO_DATA;
            return {
                ...data,
                datasets: [
                    {
                        backgroundColor: [getCustomColor(currentColorScheme, "#FAF1EB", "#3C3E4B")],
                        borderColor,
                        data: fakeData,
                        fake: true,
                        label: "",
                        trueLabels: fakeTrueLabels,
                    },
                ],
            };
        }
        return data;
    },

    getLegendOptions() {
        const { mode } = this.model.metaData;
        const legendOptions = {
            onHover: this.onLegendHover.bind(this),
            onLeave: this.onLegendLeave.bind(this),
        };
        if (mode === "line") {
            legendOptions.onClick = this.onLegendClick.bind(this);
        }
        if (mode === "pie") {
            legendOptions.labels = {
                generateLabels: (chart) =>
                    chart.data.labels.map((label, index) => {
                        const hidden = !chart.getDataVisibility(index);
                        const fullText = label;
                        const text = shortenLabel(fullText);
                        const fillStyle =
                            label === NO_DATA
                                ? NO_DATA_COLOR
                                : getBunnaGraphColor(index);
                        return {
                            text,
                            fullText,
                            fillStyle,
                            hidden,
                            index,
                            fontColor: GRAPH_LEGEND_COLOR,
                            lineWidth: 0,
                        };
                    }),
            };
        } else {
            legendOptions.position = "top";
            legendOptions.align = "end";
            const referenceColor = mode === "bar" ? "backgroundColor" : "borderColor";
            legendOptions.labels = {
                generateLabels: (chart) => {
                    const { data } = chart;
                    const labels = data.datasets.map((dataset, index) => ({
                        text: shortenLabel(dataset.label),
                        fullText: dataset.label,
                        fillStyle: dataset[referenceColor],
                        hidden: !chart.isDatasetVisible(index),
                        lineCap: dataset.borderCapStyle,
                        lineDash: dataset.borderDash,
                        lineDashOffset: dataset.borderDashOffset,
                        lineJoin: dataset.borderJoinStyle,
                        lineWidth: dataset.borderWidth,
                        strokeStyle: dataset.borderColor,
                        pointStyle: dataset.pointStyle,
                        rotation: dataset.rotation,
                        datasetIndex: index,
                        fontColor: GRAPH_LEGEND_COLOR,
                    }));
                    return labels;
                },
            };
        }
        return legendOptions;
    },
});
