/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";

const BOX_DEFS = [
  [{name:"", tier:"teal", desc:""}, {name:"", tier:"teal", desc:""}, {name:"", tier:"teal", desc:""}],
  [{name:"", tier:"teal", desc:""}, {name:"", tier:"teal", desc:""}, {name:"", tier:"teal", desc:""}],
  [{name:"", tier:"teal", desc:""}, {name:"", tier:"teal", desc:""}, {name:"", tier:"teal", desc:""}]
];

const TIER_COLOR = { gold:"#726732", teal:"#425727", brick:"#541718", purple:"#6B21A8", amber:"#B45309", slate:"#475569" };
const READY_CLASS = { ready_now:"r-now", ready_1_2:"r-soon", ready_3_5:"r-later" };
const READY_LABEL = { ready_now:"Ready Now", ready_1_2:"Ready Soon (1–2 yrs)", ready_3_5:"Ready Later (3–5 yrs)" };
const CRITICAL_CATEGORIES = ["Executive Leadership","Specialized Technical","High Regulatory / Business-Risk","Key Operational Management"];

export class NineBoxGrid extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        
        this.state = useState({
            people: [],
            activeRole: "ppdd",
            selectedId: null,
            tipShow: false,
            tipX: 0,
            tipY: 0,
            tipTitle: "",
            tipSub: "",
            tipReady: "",
            tipCritical: "",
            
            boxDefs: BOX_DEFS,
            roleDefs: [
              {key:"ppdd", label:"PPDD / SPMC"},
              {key:"manager", label:"Manager"},
              {key:"employee", label:"Employee"},
            ],
            roleNotes: {
              ppdd:"",
              manager:"Viewing as Manager: names outside your reporting line are masked as initials only, per role-based access control (FR-GOV-002).",
              employee:"Viewing as Employee: succession readiness and critical-position linkage are confidential and hidden. Employees have view-only access to career paths (Business Rule, §1.3).",
            },
            readinessLevels: [],
            criticalCategories: CRITICAL_CATEGORIES,
        });

        onWillStart(async () => {
            await this.loadData();
        });
    }

    async loadData() {
        // 2. Fetch dynamic Readiness Levels from Odoo model succession.readiness.level
        try {
            const dbReadiness = await this.orm.searchRead(
                "succession.readiness.level",
                [],
                ["id", "name", "sequence", "is_ready_for_deployment"],
                { order: "sequence, id" }
            );
            if (dbReadiness && dbReadiness.length > 0) {
                this.state.readinessLevels = dbReadiness;
            }
        } catch (e) {
            console.warn("Using default readiness levels.", e);
        }

        // 2b. Fetch dynamic Criticality Categories from Odoo model succession.criticality.category
        try {
            const dbCategories = await this.orm.searchRead(
                "succession.criticality.category",
                [],
                ["id", "name"]
            );
            if (dbCategories && dbCategories.length > 0) {
                this.state.criticalCategories = dbCategories.map(c => c.name);
            }
        } catch (e) {
            console.warn("Could not load criticality categories from database.", e);
        }

        // 3. Fetch dynamic 9-box cell definitions from Odoo model succession.ninebox.cell
        try {
            const cells = await this.orm.searchRead(
                "succession.ninebox.cell",
                [],
                ["performance_rating", "potential_rating", "name", "tier_color", "description", "min_pms_score", "max_pms_score", "min_potential_match", "max_potential_match"],
                { order: "sequence, id" }
            );
            if (cells && cells.length > 0) {
                const perfMap = {'low': 0, 'medium': 1, 'high': 2};
                const potMap = {'low': 0, 'medium': 1, 'high': 2};
                const newDefs = JSON.parse(JSON.stringify(BOX_DEFS));
                cells.forEach(c => {
                    const r = potMap[c.potential_rating];
                    const col = perfMap[c.performance_rating];
                    if (r !== undefined && col !== undefined && newDefs[r] && newDefs[r][col]) {
                        const rangeInfo = `Qualifying Range: PMS [${c.min_pms_score || 0} - ${c.max_pms_score || 100}] | Competency Match [${c.min_potential_match || 0}% - ${c.max_potential_match || 100}%]`;
                        newDefs[r][col] = {
                            name: c.name,
                            tier: c.tier_color || 'teal',
                            desc: c.description ? `${c.description}\n\n${rangeInfo}` : rangeInfo,
                            min_pms: c.min_pms_score,
                            max_pms: c.max_pms_score,
                            min_pot: c.min_potential_match,
                            max_pot: c.max_potential_match
                        };
                    }
                });
                this.state.boxDefs = newDefs;
            }
        } catch (e) {
            console.warn("Could not load custom 9-box cell definitions, falling back to defaults.", e);
        }

        // 4. Fetch candidates from Odoo model succession.candidate
        const candidates = await this.orm.searchRead(
            "succession.candidate",
            [],
            [
                "id", "display_name", "job_id", "performance_rating", "potential_rating",
                "readiness_level_id", "critical_position_id", "competency_match_percent",
                "latest_pms_score", "nine_box_label", "write_date", "employee_id"
            ]
        );

        const perfMap = {'low': 0, 'medium': 1, 'high': 2};
        const potMap = {'low': 0, 'medium': 1, 'high': 2};
        const perfLabels = { low: "Low Performance", medium: "Medium Performance", high: "High Performance" };
        const potLabels = { low: "Low Potential", medium: "Medium Potential", high: "High Potential" };
        
        const people = [];
        
        for (let i = 0; i < candidates.length; i++) {
            let c = candidates[i];
            const pmsVal = c.latest_pms_score || 0.0;
            const compMatch = Math.round(c.competency_match_percent || 0);

            // Automatically place employee into the grid cell matching configured min/max
            let perfVal = perfMap[c.performance_rating || 'low'] ?? 0;
            let potVal = potMap[c.potential_rating || 'low'] ?? 0;

            let matchedR = -1;
            let matchedCol = -1;
            for (let r = 2; r >= 0; r--) {
                for (let col = 2; col >= 0; col--) {
                    const def = this.state.boxDefs[r] && this.state.boxDefs[r][col];
                    if (def && def.min_pms !== undefined && def.max_pms !== undefined &&
                        def.min_pot !== undefined && def.max_pot !== undefined) {
                        if (pmsVal >= def.min_pms && pmsVal <= def.max_pms &&
                            compMatch >= def.min_pot && compMatch <= def.max_pot) {
                            matchedR = r;
                            matchedCol = col;
                            break;
                        }
                    }
                }
                if (matchedR !== -1) break;
            }

            if (matchedR !== -1 && matchedCol !== -1) {
                potVal = matchedR;
                perfVal = matchedCol;
            }

            const cellPerfRating = perfVal === 2 ? 'high' : (perfVal === 1 ? 'medium' : 'low');
            const cellPotRating = potVal === 2 ? 'high' : (potVal === 1 ? 'medium' : 'low');

            const cellDef = (this.state.boxDefs[potVal] && this.state.boxDefs[potVal][perfVal])
                ? this.state.boxDefs[potVal][perfVal]
                : null;
            const cellTier = cellDef ? cellDef.tier : 'teal';

            let rClass = "";
            let rLabel = "";
            let rCode = "";
            if (c.readiness_level_id) {
                rLabel = c.readiness_level_id[1];
                const rId = c.readiness_level_id[0];
                const rMatch = this.state.readinessLevels.find(rl => rl.id === rId);
                if (rMatch) {
                    if (rMatch.is_ready_for_deployment) {
                        rClass = "r-now";
                        rCode = "ready_now";
                    } else if ((rMatch.sequence && rMatch.sequence <= 20) || rMatch.name.includes("1-2")) {
                        rClass = "r-soon";
                        rCode = "ready_soon";
                    } else {
                        rClass = "r-later";
                        rCode = "ready_later";
                    }
                } else {
                    const rLower = (rLabel || "").toLowerCase();
                    if (rLower.includes("now") || rLower.includes("0-6")) {
                        rClass = "r-now";
                        rCode = "ready_now";
                    } else if (rLower.includes("1-2")) {
                        rClass = "r-soon";
                        rCode = "ready_soon";
                    } else {
                        rClass = "r-later";
                        rCode = "ready_later";
                    }
                }
            }

            people.push({
                id: c.id,
                name: c.display_name || "Unknown",
                role: c.job_id ? c.job_id[1] : "No Title",
                track: "all",
                perf: perfVal,
                pot: potVal,
                perfRating: cellPerfRating,
                potRating: cellPotRating,
                perfLabel: perfLabels[cellPerfRating] || "Low Performance",
                potLabel: potLabels[cellPotRating] || "Low Potential",
                pms: pmsVal,
                pmsFormatted: pmsVal ? (pmsVal % 1 === 0 ? pmsVal.toFixed(0) : pmsVal.toFixed(1)) : "0.0",
                pmsPct: pmsVal <= 5.0 ? Math.min(100, Math.round((pmsVal / 5.0) * 100)) : Math.min(100, Math.round(pmsVal)),
                compMatch: compMatch,
                nineBoxLabel: (cellDef ? cellDef.name : "") || c.nine_box_label || "",
                cellMinPms: cellDef ? cellDef.min_pms : 0,
                cellMaxPms: cellDef ? cellDef.max_pms : 100,
                cellMinPot: cellDef ? cellDef.min_pot : 0,
                cellMaxPot: cellDef ? cellDef.max_pot : 100,
                ready: rCode,
                readyClass: rClass,
                readyLabel: rLabel || "Not assessed",
                critical: c.critical_position_id ? c.critical_position_id[1] : null,
                gap: Math.max(0, 100 - compMatch),
                idp: "No open actions",
                lastCal: c.write_date ? c.write_date.split(' ')[0] : "—",
                tierColor: TIER_COLOR[cellTier] || "#425727",
                isManagerMasked: false,
                emp_id: c && c.employee_id ? c.employee_id[0] : 0
            });
        }
        
        this.state.people = people;
    }
    
    // --- Drag and Drop ---
    onDragStart(e, p) {
        e.dataTransfer.setData("text/plain", p.id);
        e.dataTransfer.effectAllowed = "move";
    }

    onDragOver(e) {
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
    }

    async onDrop(e, r, c) {
        e.preventDefault();
        const idStr = e.dataTransfer.getData("text/plain");
        if (!idStr) return;
        
        const id = parseInt(idStr);
        if (isNaN(id)) return;
        
        // Find the person
        const person = this.state.people.find(p => p.id === id);
        if (!person) return;
        
        // Don't update if dropped in the same cell
        if (person.pot === r && person.perf === c) return;
        
        // Map 0,1,2 to strings
        const perfMapRev = {0: 'low', 1: 'medium', 2: 'high'};
        const potMapRev = {0: 'low', 1: 'medium', 2: 'high'};
        const targetPerf = perfMapRev[c];
        const targetPot = potMapRev[r];
        
        // If it's a real record (id > 0), update it
        if (id > 0) {
            try {
                await this.orm.write("succession.candidate", [id], {
                    performance_rating: targetPerf,
                    potential_rating: targetPot
                });
            } catch (err) {
                console.error("Failed to update candidate ratings", err);
                return;
            }
        }
        
        // Update local state
        const perfLabels = { low: "Low Performance", medium: "Medium Performance", high: "High Performance" };
        const potLabels = { low: "Low Potential", medium: "Medium Potential", high: "High Potential" };
        person.pot = r;
        person.perf = c;
        person.perfRating = targetPerf;
        person.potRating = targetPot;
        person.perfLabel = perfLabels[targetPerf] || "Low Performance";
        person.potLabel = potLabels[targetPot] || "Low Potential";
        
        const cellDef = (this.state.boxDefs[r] && this.state.boxDefs[r][c]) ? this.state.boxDefs[r][c] : null;
        if (cellDef) {
            person.nineBoxLabel = cellDef.name;
            person.tierColor = TIER_COLOR[cellDef.tier] || "#425727";
            person.cellMinPms = cellDef.min_pms;
            person.cellMaxPms = cellDef.max_pms;
            person.cellMinPot = cellDef.min_pot;
            person.cellMaxPot = cellDef.max_pot;
        }
    }
    
    // --- Actions ---
    setRole(key) { this.state.activeRole = key; this.state.selectedId = null; }
    selectPerson(id) { this.state.selectedId = id; }
    openForm(id) {
        this.action.doAction({
            type: 'ir.actions.act_window',
            res_model: 'succession.candidate',
            res_id: id,
            views: [[false, 'form']],
            target: 'current'
        });
    }
    
    // --- Getters ---
    getVisiblePeople() {
        return this.state.people;
    }
    
    getDisplayName(p, isAvatar) {
        let name = p.name;
        let initials = name.split(" ").map(w=>w[0]).join("").slice(0,2).toUpperCase();
        
        if (this.state.activeRole === "employee") return isAvatar ? initials : initials + " (Hidden)";
        if (this.state.activeRole === "manager" && p.isManagerMasked) return isAvatar ? initials : initials + ".";
        return isAvatar ? initials : name;
    }
    
    getPeopleInBox(r, c) {
        return this.getVisiblePeople().filter(p => p.pot === r && p.perf === c);
    }
    
    getBoxCount(r, c) {
        return this.getPeopleInBox(r, c).length;
    }
    
    getStarsCount() { return this.getVisiblePeople().filter(p => p.pot === 2 && p.perf === 2).length; }
    getReadyNowCount() { return this.getVisiblePeople().filter(p => p.ready === "ready_now").length; }
    getCriticalLinkedCount() { return this.getVisiblePeople().filter(p => p.critical).length; }
    getAtRiskCount() { return this.getVisiblePeople().filter(p => p.pot === 2 && p.perf === 0).length; }
    
    getCalibrationText() {
        const vis = this.getVisiblePeople();
        const total = vis.length || 1;
        const cal = vis.filter(p => p.lastCal !== "—").length;
        return `${cal} of ${total} in view validated by SPMC · ${total-cal} pending calibration.`;
    }
    
    getCalibrationPct() {
        const vis = this.getVisiblePeople();
        const total = vis.length || 1;
        const cal = vis.filter(p => p.lastCal !== "—").length;
        return Math.round((cal/total)*100);
    }
    
    getSelectedPerson() {
        return this.state.people.find(p => p.id === this.state.selectedId);
    }
    
    getLegendItems() {
        if (this.state.readinessLevels && this.state.readinessLevels.length > 0) {
            return this.state.readinessLevels.map(rl => {
                let ringClass = "r-later";
                if (rl.is_ready_for_deployment) {
                    ringClass = "r-now";
                } else if ((rl.sequence && rl.sequence <= 20) || rl.name.includes("1-2")) {
                    ringClass = "r-soon";
                }
                return {
                    id: rl.id,
                    name: rl.name,
                    ringClass: ringClass,
                };
            });
        }
        return [
            { id: 'rn', name: "Ready Now (0-6 Months)", ringClass: "r-now" },
            { id: 'rs', name: "Ready in 1-2 Years", ringClass: "r-soon" },
            { id: 'rl', name: "Ready in 3-5 Years", ringClass: "r-later" },
        ];
    }
    
    getPipelineCoverage() {
        const vis = this.getVisiblePeople();
        const criticalNames = new Set();
        vis.forEach(p => {
            if (p.critical) criticalNames.add(p.critical);
        });
        
        let categories = Array.from(criticalNames);
        if (categories.length === 0) {
            categories = ["Executive Leadership", "Specialized Technical"];
        }
        
        return categories.map(cat => {
            const linked = vis.filter(p => p.critical && p.critical.includes(cat) || (p.critical && cat==="Executive Leadership")); 
            const covered = linked.filter(p => p.ready === "ready_now").length;
            const total = linked.length;
            const pct = total ? Math.round((covered/total)*100) : 0;
            return {
                name: cat,
                covered: covered,
                total: total,
                pct: total ? pct : 0,
                hasGap: (pct < 100 && total > 0)
            };
        }).slice(0, 5);
    }

    // --- Tooltip ---
    showTip(e, p, def) {
        this.state.tipTitle = (this.state.activeRole === "employee" ? this.getDisplayName(p, true) : p.name) + " — " + def.name;
        this.state.tipSub = `${p.role} | PMS: ${p.pmsFormatted} | Competency: ${p.compMatch}%`;
        this.state.tipReady = p.readyLabel || "Not yet assessed for readiness";
        this.state.tipCritical = this.state.activeRole !== "employee" ? p.critical : "";
        this.state.tipShow = true;
        this.moveTip(e);
    }
    
    moveTip(e) {
        this.state.tipX = e.clientX + 14;
        this.state.tipY = e.clientY + 14;
    }
    
    hideTip() {
        this.state.tipShow = false;
    }
}
NineBoxGrid.template = "bunna_succession_management.NineBoxGrid";

registry.category("actions").add("bunna_succession_management.nine_box_action", NineBoxGrid);
