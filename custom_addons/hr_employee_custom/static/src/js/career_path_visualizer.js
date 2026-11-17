/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class CareerPathVisualizer extends Component {
    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");

        const context = this.props.action && this.props.action.context
            ? this.props.action.context : {};
        const activeCareerPathId = context.active_career_path_id || false;
        const isAllCareerMap = Boolean(context.is_all_career_map || context.default_start_job_id);

        this.state = useState({
            graphData: null,
            loading: true,
            error: null,
            activeTab: 'vertical',
            searchQuery: '',
            selectedTargetJobId: context.default_target_job_id || null,
            selectedCareerPathId: activeCareerPathId,
            isSearchDropdownOpen: false,
            // All Career Map state (PPDD Explorer)
            isAllCareerMap: isAllCareerMap,
            selectedStartJobId: context.default_start_job_id || null,
            expandedStepNumbers: {},
            expandedCardNodeIds: {},
            expandedLateralNodeIds: {},
            zoomLevel: 1.0,
            selectedCardDetail: null,
            _treeEntered: false,   // true once user first clicks ▸ on the hero card
            isPromoTopCollapsed: false,
            isPromoBranchesExpanded: false,
            isLateralBranchesExpanded: false,
            expandedSubBranchKeys: {},
            isLat1TopCollapsed: false,
            isLat1BotCollapsed: false,
            isLat2TopCollapsed: false,
            isLat2BotCollapsed: false,
        });

        onWillStart(async () => {
            const initialTargetJobId = context.default_target_job_id || null;
            await this.loadGraphData(initialTargetJobId);
        });
    }

    goBackToPositionsList() {
        this.actionService.doAction("hr_employee_custom.action_all_career_map_positions", {
            clearBreadcrumbs: false,
        });
    }

    // ─── Data loading ────────────────────────────────────────────────────────

    async loadGraphData(targetJobId = null, careerPathId = undefined, startJobId = undefined) {
        this.state.loading = true;
        this.state.error = null;
        this.state.selectedCardDetail = null;
        try {
            const context = this.props.action && this.props.action.context
                ? this.props.action.context : {};
            const activeEmployeeId = context.active_employee_id || false;
            const pathId = careerPathId !== undefined
                ? careerPathId
                : (this.state.selectedCareerPathId || context.active_career_path_id || false);
            const actualStartJobId = startJobId !== undefined
                ? startJobId
                : (this.state.selectedStartJobId || false);

            const data = await this.orm.call(
                "hr.employee",
                "get_career_path_graph",
                [activeEmployeeId, targetJobId || false, this.state.activeTab, pathId, actualStartJobId]
            );

            if (data.error) {
                this.state.error = data.error;
            } else {
                this.state.graphData = data;
                if (data.selected_career_path_id) {
                    this.state.selectedCareerPathId = data.selected_career_path_id;
                }
                if (data.current_job_id && this.state.isAllCareerMap) {
                    this.state.selectedStartJobId = data.current_job_id;
                }
                if (data.searched_target_job) {
                    this.state.selectedTargetJobId = data.searched_target_job.id;
                    this.state.searchQuery = data.searched_target_job.name;
                    this.autoExpandTargetPath(data.card_branch_tree);
                }
            }
        } catch (e) {
            this.state.error = e.message || "Failed to load career path data.";
        } finally {
            this.state.loading = false;
        }
    }

    async onCareerPathChange(ev) {
        const pathId = parseInt(ev.target.value, 10);
        this.state.selectedCareerPathId = pathId;
        this.state.selectedTargetJobId = null;
        this.state.searchQuery = '';
        this.state.selectedStartJobId = null;
        this.state.expandedStepNumbers = {};
        this.state._treeEntered = false;
        await this.loadGraphData(null, pathId);
    }

    // ─── Tab switching ───────────────────────────────────────────────────────

    async switchTab(tabName) {
        if (this.state.activeTab === tabName) return;
        this.state.activeTab = tabName;
        this.state.expandedStepNumbers = {};
        this.state.expandedLateralNodeIds = {};
        this.state._treeEntered = false;
        this.state.isPromoBranchesExpanded = false;
        this.state.isLateralBranchesExpanded = false;
        await this.loadGraphData(this.state.selectedTargetJobId);
    }

    // ─── Search ──────────────────────────────────────────────────────────────

    onSearchInput(ev) {
        this.state.searchQuery = ev.target.value;
        this.state.isSearchDropdownOpen = true;
    }

    toggleSearchDropdown() {
        this.state.isSearchDropdownOpen = !this.state.isSearchDropdownOpen;
    }

    closeSearchDropdown() {
        this.state.isSearchDropdownOpen = false;
    }

    async selectSearchTarget(job) {
        this.state.selectedTargetJobId = job.id;
        this.state.searchQuery = job.name;
        this.state.isSearchDropdownOpen = false;
        await this.loadGraphData(job.id);
    }

    /** Quick Target chip click — forces the tab to match the movement type */
    async selectQuickTarget(qt) {
        const tabMap = { vertical: 'vertical', lateral: 'lateral', dual: 'dual' };
        const tab = tabMap[qt.movement_type] || 'vertical';

        this.state.activeTab = tab;
        this.state.selectedTargetJobId = qt.id;
        this.state.searchQuery = qt.name;
        this.state.isSearchDropdownOpen = false;
        // FIX 3: fresh objects
        this.state.expandedStepNumbers = {};
        this.state.expandedLateralNodeIds = {};

        await this.loadGraphData(qt.id);
    }

    async onSearchButtonClick() {
        this.state.isSearchDropdownOpen = false;
        const query = (this.state.searchQuery || '').trim().toLowerCase();
        if (!query) {
            await this.clearSearch();
            return;
        }

        const targets = this.availableTargetJobs;
        const exact = targets.find(j => j.name.toLowerCase() === query);
        const match = exact || targets.find(j => j.name.toLowerCase().includes(query));

        if (match) {
            await this.selectSearchTarget(match);
        } else if (this.state.selectedTargetJobId) {
            await this.loadGraphData(this.state.selectedTargetJobId);
        }
    }

    async clearSearch() {
        this.state.selectedTargetJobId = null;
        this.state.searchQuery = '';
        this.state.isSearchDropdownOpen = false;
        this.state.expandedStepNumbers = {};
        this.state._treeEntered = false;
        this.state.isPromoBranchesExpanded = false;
        this.state.isLateralBranchesExpanded = false;
        await this.loadGraphData(null);
    }

    onSearchKeyDown(ev) {
        if (ev.key === 'Enter') {
            this.onSearchButtonClick();
        }
    }

    // ─── FIX 3: Expand / Collapse — always assign new object ────────────────

    // ─── Card Tree Expand / Collapse ────────────────────────────────────────

    autoExpandTargetPath(tree) {
        if (!tree) return;
        const newMap = { ...this.state.expandedCardNodeIds, root: true };
        const expandAncestors = (node) => {
            if (!node) return;
            if (node.has_target) {
                newMap[node.id] = true;
            }
            if (node.children) {
                for (const c of node.children) expandAncestors(c);
            }
        };
        expandAncestors(tree);
        this.state._treeEntered = true;
        this.state.expandedCardNodeIds = newMap;
    }

    toggleCardExpand(nodeId) {
        const current = this.state.expandedCardNodeIds;
        const wasOpen = this.isCardExpanded(nodeId);
        this.state._treeEntered = true;

        const next = { ...current };
        if (wasOpen) {
            next[nodeId] = false;
        } else {
            next[nodeId] = true;
        }
        this.state.expandedCardNodeIds = next;
    }

    isCardExpanded(nodeId) {
        if (this.state.expandedCardNodeIds[nodeId] !== undefined) {
            return Boolean(this.state.expandedCardNodeIds[nodeId]);
        }
        if (nodeId === 'root') {
            return Boolean(this.isTargetSearched || this.state._treeEntered);
        }
        return false;
    }

    toggleStepExpand(stepNumber) {
        if (stepNumber === 0) {
            this.toggleCardExpand('root');
            return;
        }
        const current = this.state.expandedStepNumbers;
        if (current[stepNumber]) {
            // Collapse this step's children and everything below
            const next = {};
            for (const s in current) {
                if (Number(s) < stepNumber) next[s] = true;
            }
            this.state.expandedStepNumbers = next;
        } else {
            // Mark tree as entered so collapse doesn't jump to hero card
            this.state._treeEntered = true;
            this.state.expandedStepNumbers = { ...current, [stepNumber]: true };
            setTimeout(() => {
                const el = document.getElementById(`cpv-level-row-${stepNumber + 1}`);
                if (el) el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }, 120);
        }
    }

    isStepExpanded(stepNumber) {
        if (stepNumber === 0) {
            return this.isCardExpanded('root');
        }
        if (this.isTargetSearched) return true;
        return Boolean(this.state.expandedStepNumbers[stepNumber]);
    }

    toggleLateralExpand(nodeId) {
        const current = this.state.expandedLateralNodeIds;
        const wasOpen = Boolean(current[nodeId]);
        this.state.expandedLateralNodeIds = { ...current, [nodeId]: !wasOpen };
        if (!wasOpen) {
            setTimeout(() => {
                const el = document.getElementById(`cpv-lateral-drawer-${nodeId}`);
                if (el) el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }, 120);
        }
    }

    isLateralExpanded(nodeId) {
        return Boolean(this.state.expandedLateralNodeIds[nodeId]);
    }

    expandAll() {
        this.state._treeEntered = true;
        const newMap = { root: true };
        const markAll = (node) => {
            if (!node) return;
            newMap[node.id] = true;
            if (node.children) {
                for (const c of node.children) markAll(c);
            }
        };
        markAll(this.cardBranchTree);
        for (let i = 0; i < this.hierarchyTree.length; i++) newMap[i] = true;
        this.state.expandedStepNumbers = newMap;
        this.state.expandedCardNodeIds = newMap;
    }

    collapseAll() {
        this.state.expandedStepNumbers = {};
        this.state.expandedCardNodeIds = {};
        this.state.expandedLateralNodeIds = {};
        this.state.isPromoBranchesExpanded = false;
        this.state.isLateralBranchesExpanded = false;
        this.state._treeEntered = false;
        if (this.state.selectedTargetJobId) this.clearSearch();
    }

    // ─── Branching Visualizer Toggles ────────────────────────────────────────

    togglePromoBranches() {
        this.state.isPromoBranchesExpanded = !this.state.isPromoBranchesExpanded;
    }

    toggleLateralBranches() {
        this.state.isLateralBranchesExpanded = !this.state.isLateralBranchesExpanded;
    }

    togglePromoTop() {
        this.state.isPromoTopCollapsed = !this.state.isPromoTopCollapsed;
    }

    toggleLat1Top() {
        this.state.isLat1TopCollapsed = !this.state.isLat1TopCollapsed;
    }

    toggleLat1Bot() {
        this.state.isLat1BotCollapsed = !this.state.isLat1BotCollapsed;
    }

    toggleLat2Top() {
        this.state.isLat2TopCollapsed = !this.state.isLat2TopCollapsed;
    }

    toggleLat2Bot() {
        this.state.isLat2BotCollapsed = !this.state.isLat2BotCollapsed;
    }

    // ─── Zoom ────────────────────────────────────────────────────────────────

    zoomIn() {
        this.state.zoomLevel = Math.min(1.3, +(this.state.zoomLevel + 0.1).toFixed(2));
    }

    zoomOut() {
        this.state.zoomLevel = Math.max(0.7, +(this.state.zoomLevel - 0.1).toFixed(2));
    }

    // ─── Preview best path ───────────────────────────────────────────────────

    async previewBestPath() {
        const tree = this.hierarchyTree;
        let bestTarget = null;
        if (tree.length > 1) {
            const lastStep = tree[tree.length - 1];
            bestTarget = { id: lastStep.main_node.job_id, name: lastStep.main_node.job_name };
        }
        if (!bestTarget) {
            const targets = this.availableTargetJobs;
            const mgr = targets.find(t =>
                t.name.toLowerCase().includes('manager') || t.name.toLowerCase().includes('lead'));
            bestTarget = mgr || targets[0];
        }
        if (bestTarget) {
            await this.selectSearchTarget(bestTarget);
        } else {
            this.expandAll();
        }
    }

    // ─── Getters ─────────────────────────────────────────────────────────────

    get isTargetSearched() {
        return Boolean(this.state.graphData && this.state.graphData.searched_target_job);
    }

    get hierarchyTree() {
        return this.state.graphData?.hierarchy_tree || [];
    }

    get rootNode() {
        return this.state.graphData?.root_node || null;
    }

    get rootStep() {
        return this.hierarchyTree.length > 0 ? this.hierarchyTree[0] : null;
    }

    get treeLevels() {
        const tree = this.hierarchyTree;
        if (tree.length <= 1) return [];
        if (this.isTargetSearched) return tree.slice(1);
        const levels = [];
        for (let i = 1; i < tree.length; i++) {
            if (this.isStepExpanded(i - 1)) {
                levels.push(tree[i]);
            } else {
                break;
            }
        }
        return levels;
    }

    get cardBranchTree() {
        return this.state.graphData?.card_branch_tree || null;
    }

    get visibleTimelineCards() {
        if (!this.cardBranchTree) return [];
        if (!this.isCardExpanded('root')) return [];

        const result = [];
        const traverse = (node, level, parentId) => {
            const isExp = this.isCardExpanded(node.id);
            const isTarget = Boolean(node.is_target);
            result.push({
                id: node.id,
                uniqueKey: `${parentId}_${node.id}_${level}`,
                level: level,
                step_number: level,
                node: node,
                child_count: node.children ? node.children.length : 0,
                has_children: Boolean(node.children && node.children.length > 0),
                is_expanded: isExp,
                is_target: isTarget,
                movement_type: node.movement_type || 'vertical',
                parent_id: parentId,
            });

            if (isExp && node.children && node.children.length > 0) {
                for (const child of node.children) {
                    traverse(child, level + 1, node.id);
                }
            }
        };

        const children = this.cardBranchTree.children || [];
        for (const child of children) {
            traverse(child, 1, 'root');
        }
        return result;
    }

    get suggestedNextMoves() {
        return this.state.graphData?.suggested_next_moves || [];
    }

    get quickTargets() {
        return this.state.graphData?.quick_targets || [];
    }

    get branchingPromotion() {
        return this.state.graphData?.branching_promotion || null;
    }

    get branchingLateral() {
        return this.state.graphData?.branching_lateral || null;
    }

    computeBracketLayout(numArms) {
        if (numArms <= 1) {
            return { arm_positions: [50], arm_min_y: 50, arm_max_y: 50 };
        }
        const positions = [];
        for (let i = 0; i < numArms; i++) {
            positions.push(Math.round(((i + 0.5) / numArms) * 100));
        }
        return {
            arm_positions: positions,
            arm_min_y: positions[0],
            arm_max_y: positions[positions.length - 1],
        };
    }

    computeWeightedBracketLayout(items) {
        if (!items || !items.length) return null;
        if (items.length === 1 && (!items[0].sub_branches || items[0].sub_branches.length <= 1)) {
            return { arm_positions: [50], arm_min_y: 50, arm_max_y: 50 };
        }
        const weights = items.map(it => {
            if (it.has_sub_branches) {
                const visibleSub = this.displayedSubBranches(it);
                return Math.max(1, visibleSub.length);
            }
            if (it.weight !== undefined) return it.weight;
            return Math.max(1, (it.sub_branches ? it.sub_branches.length : 1));
        });
        const totalW = weights.reduce((a, b) => a + b, 0);
        let cum = 0;
        const positions = [];
        for (const w of weights) {
            const pos = Math.round(((cum + w / 2.0) / totalW) * 100);
            positions.push(pos);
            cum += w;
        }
        return {
            arm_positions: positions,
            arm_min_y: positions[0],
            arm_max_y: positions[positions.length - 1],
        };
    }

    displayedSubBranches(item) {
        if (!item || !item.sub_branches) return [];
        const key = item.primary_role ? item.primary_role.id : 'sub';
        if (this.state.expandedSubBranchKeys[key] || item.sub_branches.length <= 3) {
            return item.sub_branches;
        }
        return item.sub_branches.slice(0, 3);
    }

    hiddenSubBranchesCount(item) {
        if (!item || !item.sub_branches) return 0;
        return Math.max(0, item.sub_branches.length - 3);
    }

    isSubBranchesExpanded(item) {
        const key = item.primary_role ? item.primary_role.id : 'sub';
        return Boolean(this.state.expandedSubBranchKeys[key]);
    }

    toggleSubBranches(item) {
        const key = item.primary_role ? item.primary_role.id : 'sub';
        const current = this.state.expandedSubBranchKeys;
        this.state.expandedSubBranchKeys = {
            ...current,
            [key]: !current[key],
        };
    }

    subBranchLayout(item) {
        const branches = this.displayedSubBranches(item);
        return this.computeBracketLayout(branches.length);
    }

    get displayedPromoBranches() {
        const bp = this.branchingPromotion;
        if (!bp) return [];
        if (bp.branch_items && bp.branch_items.length) {
            if (this.state.isPromoBranchesExpanded || bp.branch_items.length <= 3) {
                return bp.branch_items;
            }
            return bp.branch_items.slice(0, 3);
        }
        if (!bp.branches) return [];
        if (this.state.isPromoBranchesExpanded || bp.branches.length <= 3) {
            return bp.branches;
        }
        return bp.branches.slice(0, 3);
    }

    get hiddenPromoBranchesCount() {
        const bp = this.branchingPromotion;
        if (!bp) return 0;
        const total = bp.branch_items ? bp.branch_items.length : (bp.branches ? bp.branches.length : 0);
        return Math.max(0, total - 3);
    }

    get promoBracketLayout() {
        const bp = this.branchingPromotion;
        if (!bp) return null;
        if (bp.has_primary_pivot) {
            if (this.state.isPromoTopCollapsed) {
                return { arm_positions: [50], arm_min_y: 50, arm_max_y: 50 };
            }
            return {
                arm_positions: bp.arm_positions,
                arm_min_y: bp.arm_min_y,
                arm_max_y: bp.arm_max_y,
            };
        }
        if (bp.branch_items && bp.branch_items.length) {
            const items = this.displayedPromoBranches;
            return this.computeWeightedBracketLayout(items);
        }
        const count = this.displayedPromoBranches.length;
        return this.computeBracketLayout(count);
    }

    get displayedLateralBranches() {
        const bl = this.branchingLateral;
        if (!bl) return [];
        if (bl.branch_items && bl.branch_items.length) {
            if (this.state.isLateralBranchesExpanded || bl.branch_items.length <= 3) {
                return bl.branch_items;
            }
            return bl.branch_items.slice(0, 3);
        }
        if (!bl.branches) return [];
        if (this.state.isLateralBranchesExpanded || bl.branches.length <= 3) {
            return bl.branches;
        }
        return bl.branches.slice(0, 3);
    }

    get hiddenLateralBranchesCount() {
        const bl = this.branchingLateral;
        if (!bl) return 0;
        const total = bl.branch_items ? bl.branch_items.length : (bl.branches ? bl.branches.length : 0);
        return Math.max(0, total - 3);
    }

    get lateralBracketLayout() {
        const bl = this.branchingLateral;
        if (!bl) return null;
        const count = this.displayedLateralBranches.length;
        return this.computeBracketLayout(count);
    }

    get availableTargetJobs() {
        return this.state.graphData?.available_target_jobs || [];
    }

    get availableCareerPaths() {
        return this.state.graphData?.available_career_paths || [];
    }

    get selectedCareerPathId() {
        return this.state.selectedCareerPathId || this.state.graphData?.selected_career_path_id || null;
    }

    get selectedCareerPathName() {
        const pathId = this.selectedCareerPathId;
        const found = this.availableCareerPaths.find(p => p.id === pathId);
        return found ? found.name : (this.state.graphData?.track_name || '');
    }

    get filteredTargetJobs() {
        const query = (this.state.searchQuery || '').trim().toLowerCase();
        const list = this.availableTargetJobs;
        if (!query) return list;
        return list.filter(j => j.name.toLowerCase().includes(query));
    }

    get showSearchDropdown() {
        return Boolean(this.state.isSearchDropdownOpen && this.filteredTargetJobs.length > 0);
    }

    get isInitialState() {
        // Show the hero-card view only before the user has ever interacted
        // (no target searched, no steps expanded, and graphData just loaded).
        // Once the tree view is entered it stays — collapsing pills just hides
        // child levels, it does NOT jump back to the hero card.
        return !this.isTargetSearched &&
               Object.keys(this.state.expandedStepNumbers).length === 0 &&
               Object.keys(this.state.expandedCardNodeIds).length === 0 &&
               !this.state._treeEntered;
    }

    get activeStepperStep() {
        if (this.isTargetSearched) return 3;
        if (this.isCardExpanded('root')) return 2;
        return 1;
    }

    get employeeInfo() {
        if (this.state.isAllCareerMap) {
            const jobName = this.state.graphData?.current_job || 'Select a Position';
            const dept = this.state.graphData?.department_name || '';
            const grade = this.state.graphData?.current_grade || '';
            const subTitle = [dept, grade].filter(Boolean).join(' · ');
            return {
                name: jobName,
                initials: this.state.graphData?.current_job_initials || 'CP',
                job: subTitle || 'Defined Position',
                jobInitials: this.state.graphData?.current_job_initials || 'CP',
                department: dept,
                grade: grade,
                tenure: 'Organizational View',
                pms: this.state.graphData?.current_pms || 75.0,
                trackName: this.state.graphData?.track_name || 'Career Architecture',
                employeeCount: this.state.graphData?.root_node?.employee_count || 0,
            };
        }
        return {
            name: this.state.graphData?.employee_name || 'Mitchell Admin',
            initials: this.state.graphData?.employee_initials || 'MA',
            job: this.state.graphData?.current_job || 'Junior Accountant',
            jobInitials: this.state.graphData?.current_job_initials || 'JA',
            department: this.state.graphData?.department_name || 'Finance Dept.',
            grade: this.state.graphData?.current_grade || 'Gr. 5',
            tenure: this.state.graphData?.current_tenure !== undefined
                ? `${this.state.graphData.current_tenure} years experience` : '0 years experience',
            pms: this.state.graphData?.current_pms || 3.5,
            trackName: this.state.graphData?.track_name || 'Accounting & Finance · Job Family',
            employeeCount: this.state.graphData?.root_node?.employee_count || 18,
        };
    }

    get totalTargetSteps() {
        if (this.state.graphData?.target_step_depth) {
            return this.state.graphData.target_step_depth;
        }
        if (this.isTargetSearched && this.hierarchyTree.length > 1) {
            return this.hierarchyTree.length - 1;
        }
        if (this.cardBranchTree) {
            let maxD = 1;
            const findMax = (n, d) => {
                if (!n) return;
                if (d > maxD) maxD = d;
                if (n.children) {
                    for (const c of n.children) findMax(c, d + 1);
                }
            };
            findMax(this.cardBranchTree, 0);
            return maxD;
        }
        return 3;
    }

    get categoryInfo() {
        return this.state.graphData?.category_info || {
            title: 'Promotion Path (Upward Hierarchy)',
            description: 'Promotion progression moves upward through increasing job grades.',
            badge: '↑ PROMOTION · UPWARD LADDER',
            type: this.state.activeTab,
            definition_tag: 'Same Job Family · Higher Grade',
        };
    }

    get categoryCounts() {
        // Count actual quick targets per movement type — this reflects what is
        // truly defined in the career path for the employee's current position.
        const qt = this.quickTargets;
        return {
            vertical: qt.filter(t => t.movement_type === 'vertical').length || 0,
            lateral:  qt.filter(t => t.movement_type === 'lateral').length  || 0,
            dual:     qt.filter(t => t.movement_type === 'dual').length     || 0,
        };
    }

    /** FIX 1: when on the lateral tab the "main spine" nodes ARE the lateral ones */
    get isLateralTab() {
        return this.state.activeTab === 'lateral';
    }

    /** true when on the vertical/promotion tab — lateral column must be hidden */
    get isVerticalTab() {
        return this.state.activeTab === 'vertical';
    }

    /**
     * True when no career path of any kind is defined for this position.
     * Used to show the global "no path defined" empty state.
     */
    get hasNoCareerPath() {
        if (!this.state.graphData) return false;
        if (this.state.graphData.has_career_path !== undefined) {
            return !this.state.graphData.has_career_path;
        }
        return (
            this.quickTargets.length === 0 &&
            this.hierarchyTree.length === 0 &&
            (!this.cardBranchTree || !this.cardBranchTree.children || this.cardBranchTree.children.length === 0)
        );
    }

    /**
     * True when the current tab has no data at all (lateral/dual not defined).
     * Only meaningful when hasNoCareerPath is false (a path exists, just not for this tab).
     */
    get currentTabIsEmpty() {
        if (!this.state.graphData) return false;
        if (this.isTargetSearched) return false;   // a target was found — never empty
        const tab = this.state.activeTab;
        const qt = this.quickTargets;
        if (tab === 'lateral') return qt.filter(t => t.movement_type === 'lateral').length === 0;
        if (tab === 'dual')    return qt.filter(t => t.movement_type === 'dual').length === 0;
        if (tab === 'vertical') return qt.filter(t => t.movement_type === 'vertical').length === 0;
        return false;
    }

    get tabEmptyLabel() {
        const labels = {
            lateral: 'Lateral Transfer Path',
            dual: 'Dual-Career (Expert) Path',
            vertical: 'Promotion Path',
        };
        return labels[this.state.activeTab] || 'Career Path';
    }

    getCompetencyLevelWidth(lvl) {
        const val = Number(lvl) || 0;
        const pct = Math.min(Math.max((val / 4.0) * 100, 10), 100);
        return `${pct}%`;
    }

    openCardDetail(cardNode) {
        this.state.selectedCardDetail = cardNode || null;
    }

    closeCardDetail() {
        this.state.selectedCardDetail = null;
    }

    formatJobDescription(rawHtml) {
        if (!rawHtml) return '';
        try {
            const doc = new DOMParser().parseFromString(String(rawHtml), 'text/html');
            return (doc.body?.textContent || '').replace(/\s+/g, ' ').trim();
        } catch {
            return String(rawHtml).replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
        }
    }

    openJobPositionForm(jobId) {
        if (!jobId) return;
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "hr.job",
            res_id: jobId,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

CareerPathVisualizer.template = "hr_employee_custom.CareerPathVisualizer";
registry.category("actions").add("career_path_visualizer", CareerPathVisualizer);
