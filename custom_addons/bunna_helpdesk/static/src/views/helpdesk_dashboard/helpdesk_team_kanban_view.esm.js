import {HelpdeskDashboard} from "./helpdesk_dashboard.esm";
import {KanbanRenderer} from "@web/views/kanban/kanban_renderer";
import {KanbanController} from "@web/views/kanban/kanban_controller";
import {kanbanView} from "@web/views/kanban/kanban_view";
import {registry} from "@web/core/registry";

export class HelpdeskKanbanViewRenderer extends KanbanRenderer {
    static template = "bunna_helpdesk.HelpdeskKanbanView";
    static components = Object.assign({}, KanbanRenderer.components, {
        HelpdeskDashboard,
    });
}

export class HelpdeskKanbanController extends KanbanController {
    get display() {
        return {
            ...(this.props.display || {}),
            controlPanel: false,
        };
    }
}

export const HelpdeskKanbanView = {
    ...kanbanView,
    Controller: HelpdeskKanbanController,
    Renderer: HelpdeskKanbanViewRenderer,
};

registry.category("views").add("helpdesk_kanban", HelpdeskKanbanView);
