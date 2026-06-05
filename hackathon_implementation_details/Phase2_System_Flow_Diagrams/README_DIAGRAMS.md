# Professional Diagrams for Hackathon Submission

This directory contains all Phase 2 diagrams in professional formats ready for hackathon submission.

## 📁 Files Included

### PlantUML Files (.puml)
1. **sequence_diagram.puml** - Complete ticket processing flow
2. **state_transition_diagram.puml** - Ticket lifecycle states

### Draw.io Files (.drawio)
3. **data_flow_diagram_level0.drawio** - Context diagram
4. **data_flow_diagram_level1.drawio** - Process decomposition
5. **entity_relationship_diagram_basic.drawio** - ERD (6 categories)
6. **entity_relationship_diagram_granular.drawio** - ERD (24 subcategories)

---

## 🚀 How to Use These Files

### For PlantUML Files (.puml)

**Option 1: Online Rendering (Quickest)**
1. Go to http://www.plantuml.com/plantuml/
2. Click "Upload" or paste the .puml code
3. Download as PNG or SVG (high resolution)

**Option 2: VSCode Extension**
1. Install "PlantUML" extension in VSCode
2. Open the .puml file
3. Press Alt+D to preview
4. Right-click → "Export Current Diagram" → Choose PNG/SVG/PDF

**Option 3: Command Line (for batch processing)**
```bash
# Install PlantUML
brew install plantuml  # macOS
# or
sudo apt-get install plantuml  # Linux

# Generate diagrams
plantuml sequence_diagram.puml -tpng
plantuml state_transition_diagram.puml -tsvg
```

### For Draw.io Files (.drawio)

**Option 1: Draw.io Web App (No Installation)**
1. Go to https://app.diagrams.net/
2. Click "Open Existing Diagram"
3. Select the .drawio file
4. Edit if needed
5. File → Export As → PNG/SVG/PDF

**Option 2: Draw.io Desktop App**
1. Download from https://github.com/jgraph/drawio-desktop/releases
2. Open the .drawio file
3. Export to desired format

---

## 📊 Recommended Export Settings

### For PowerPoint Presentations
- Format: **PNG**
- Resolution: **300 DPI**
- Background: **Transparent** or **White**

### For PDF Documentation
- Format: **SVG** or **PDF**
- Ensure text is searchable/selectable

### For Print Submissions
- Format: **PNG** or **PDF**
- Resolution: **300 DPI minimum**
- Color Mode: **RGB** (for screens) or **CMYK** (for print)

---

## 🎨 Diagram Descriptions

### 1. Sequence Diagram
**File:** sequence_diagram.puml  
**Shows:** Time-ordered interaction between 11 components from ticket arrival to resolution  
**Key Features:**
- Auto-numbering of steps
- Color-coded actors (ITSM, API, Agents, LLM)
- Three routing paths (auto-resolve, dept-route, escalate)
- Performance annotations (latency targets)
- Feedback loop for active learning

**Best Export:** PNG at 300 DPI for presentations

---

### 2. State Transition Diagram
**File:** state_transition_diagram.puml  
**Shows:** 12 ticket lifecycle states with transition conditions  
**Key Features:**
- Color-coded states (initial, processing, routing, active, final)
- Guard conditions on transitions
- Performance targets per state
- Rare edge cases (REOPENED state)

**Best Export:** SVG for scalability, PNG for presentations

---

### 3. Data Flow Diagram - Level 0 (Context)
**File:** data_flow_diagram_level0.drawio  
**Shows:** System boundary with external entities  
**Key Features:**
- ITSM Systems, IT Support Staff, Data Sources
- High-level data flows (Ticket Data, Resolutions, Feedback)
- System as single process

**Best Export:** PNG or SVG

---

### 4. Data Flow Diagram - Level 1 (Decomposition)
**File:** data_flow_diagram_level1.drawio  
**Shows:** 8 core processes (P1-P8) and 8 data stores (D1-D8)  
**Key Features:**
- Process circles with numbers (P1-P8)
- Data store parallel lines (D1-D8)
- Detailed data flows between components
- External entities (ITSM, Staff)

**Best Export:** PNG at high resolution (large diagram)

---

### 5. Entity Relationship Diagram - Basic (6 Categories)
**File:** entity_relationship_diagram_basic.drawio  
**Shows:** Database schema with 6 main categories  
**Key Features:**
- 20+ entities with attributes
- Crow's foot notation for relationships
- Primary/foreign key indicators
- Simplified category structure

**Best Export:** PNG or PDF

---

### 6. Entity Relationship Diagram - Granular (24 Subcategories)
**File:** entity_relationship_diagram_granular.drawio  
**Shows:** Database schema with 24 subcategories  
**Key Features:**
- Additional CATEGORIES and SUBCATEGORIES tables
- Many-to-one relationships
- Specialized department mappings
- Resolution templates per subcategory

**Best Export:** PNG or PDF

---

## ✅ Quality Checklist Before Submission

- [ ] All text is legible at normal viewing size
- [ ] Colors are professional and consistent
- [ ] Arrows and connections are clear
- [ ] Labels are positioned without overlaps
- [ ] Export resolution is 300 DPI or higher
- [ ] File format matches submission requirements
- [ ] Diagram fits on standard page size (A4 or Letter)

---

## 🛠️ Troubleshooting

**Problem:** PlantUML rendering fails  
**Solution:** Check for syntax errors, ensure all states/actors are declared

**Problem:** Draw.io file won't open  
**Solution:** Use latest version of Draw.io, try web app if desktop fails

**Problem:** Export is blurry  
**Solution:** Increase DPI to 300 or use SVG format (vector graphics)

**Problem:** Diagram too large for one page  
**Solution:** 
- Split into multiple pages
- Reduce font size slightly
- Use landscape orientation
- Export as multi-page PDF

---

## 📞 Need Help?

If diagrams need adjustments:
1. Open the source file (.puml or .drawio)
2. Make edits directly in the tool
3. Re-export to your desired format

All diagrams are fully editable and can be customized for your specific needs.

---

**Created by:** Trail Blazers Team  
**Date:** 2026  
**Purpose:** Hackathon Round 2 - Professional Diagram Submission
