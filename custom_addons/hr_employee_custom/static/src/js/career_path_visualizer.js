/** @odoo-module **/

import { Component, useState, onWillStart, useEffect, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadJS } from "@web/core/assets";

export class CareerPathVisualizer extends Component {
    setup() {
        this.orm = useService("orm");

        this.state = useState({
            graphData: null,
            loading: true,
            error: null,
            selectedVerticalNode: null,
            selectedLateralNode: null,
            selectedDualNode: null,
            activeTab: 'vertical',
        });

        onWillStart(async () => {
            await this.loadGraphData();
        });
    }

    async loadGraphData() {
        try {
            // Check context for active_employee_id (passed when opened from an employee profile)
            const context = this.props.action && this.props.action.context ? this.props.action.context : {};
            const activeEmployeeId = context.active_employee_id || false;
            
            const data = await this.orm.call(
                "hr.employee",
                "get_career_path_graph",
                [activeEmployeeId]
            );
            if (data.error) {
                this.state.error = data.error;
            } else {
                this.state.graphData = data;
            }
        } catch (e) {
            this.state.error = e.message || "Failed to load career path data.";
        } finally {
            this.state.loading = false;
        }
    }

    switchTab(tabName) {
        this.state.activeTab = tabName;
    }

    get verticalNodes() {
        if (!this.state.graphData || !this.state.graphData.nodes) return [];
        const nodes = this.state.graphData.nodes;
        const currIndex = nodes.findIndex(n => n.is_current);
        // Only show nodes that come AFTER the current job in the sequence
        return nodes.filter((n, idx) => idx > currIndex && n.movement_type === "vertical");
    }

    get lateralNodes() {
        if (!this.state.graphData || !this.state.graphData.nodes) return [];
        const nodes = this.state.graphData.nodes;
        const currIndex = nodes.findIndex(n => n.is_current);
        return nodes.filter((n, idx) => idx > currIndex && n.movement_type === "lateral");
    }

    get dualNodes() {
        if (!this.state.graphData || !this.state.graphData.nodes) return [];
        const nodes = this.state.graphData.nodes;
        const currIndex = nodes.findIndex(n => n.is_current);
        return nodes.filter((n, idx) => idx > currIndex && n.movement_type === "dual_career");
    }

    selectNode(node, type) {
        if (!node || node.is_current) return;
        if (type === 'vertical') {
            this.state.selectedVerticalNode = this.state.selectedVerticalNode?.id === node.id ? null : node;
        } else if (type === 'lateral') {
            this.state.selectedLateralNode = this.state.selectedLateralNode?.id === node.id ? null : node;
        } else if (type === 'dual') {
            this.state.selectedDualNode = this.state.selectedDualNode?.id === node.id ? null : node;
        }
    }

    groupCompetenciesByPillar(node) {
        if (!node || !node.requirements || !node.requirements.competencies) return {};
        const comps = node.requirements.competencies;
        const grouped = {};
        for (let c of comps) {
            if (!grouped[c.pillar]) {
                grouped[c.pillar] = [];
            }
            grouped[c.pillar].push(c);
        }
        return grouped;
    }

    getGapsCount(node) {
        if (!node || !node.requirements || !node.requirements.competencies) return 0;
        return node.requirements.competencies.filter(c => c.gap < 0).length;
    }

    getPillarGapsCount(comps) {
        if (!comps || !Array.isArray(comps)) return 0;
        return comps.filter(c => c.gap < 0).length;
    }

    togglePillar(ev) {
        const section = ev.currentTarget.closest('.comp-pillar-section');
        if (section) {
            section.classList.toggle('expanded');
        }
    }
}

CareerPathVisualizer.template = "hr_employee_custom.CareerPathVisualizer";
registry.category("actions").add("career_path_visualizer", CareerPathVisualizer);