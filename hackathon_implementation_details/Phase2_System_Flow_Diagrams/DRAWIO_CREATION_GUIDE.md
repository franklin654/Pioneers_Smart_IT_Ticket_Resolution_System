# Draw.io Diagram Creation Guide

Since Draw.io XML is complex and best created visually, here's a step-by-step guide to recreate the diagrams professionally in Draw.io:

## 🎨 Data Flow Diagram - Level 0 (Context)

### Step 1: Open Draw.io
1. Go to https://app.diagrams.net/
2. Create New Diagram → Blank Diagram
3. Name it: "Data_Flow_Diagram_Level0"

### Step 2: Add Shapes

**External Entities (Rectangles):**
1. Drag "Rectangle" from left panel
2. Create 3 rectangles:
   - ITSM Systems (ServiceNow, Jira)
   - IT Support Staff (L1, L2, L3)
   - Data Sources (Kaggle, Synthetic)
3. Format: Fill #667eea, Text white, Bold

**Central System (Circle):**
1. Insert → Shape → Ellipse
2. Label: "AI Ticket Routing & Resolution System"
3. Format: Fill #8b5cf6, Text white, Bold, Size: Large

**Data Flows (Arrows):**
1. Use "Connector" tool
2. Add labeled arrows:
   - ITSM → System: "Ticket Data"
   - Data Sources → System: "Training Data"
   - System → Staff: "Resolutions"
   - Staff → System: "Feedback"
3. Format: Line width 2pt, Arrow ends, Color #667eea

### Step 3: Add System Boundary
1. Insert → Shape → Rectangle with dashed border
2. Label: "System Boundary"
3. Format: No fill, Dashed line, Color #9ca3af

### Step 4: Export
File → Export As → PNG (300 DPI, Transparent background)

---

## 🔄 Data Flow Diagram - Level 1 (Process Decomposition)

### Shapes Needed:

**Processes (Circles):**
- P1: Ingest & Validate
- P2: Generate Embeddings
- P3: Classify Ticket
- P4: RAG Retrieval
- P5: Generate Resolution
- P6: Evaluate & Route
- P7: Collect Feedback
- P8: Update KB

Format: Circles, numbered, colored differently

**Data Stores (Parallel Lines):**
- D1: Tickets DB
- D2: Vector Store
- D3: Knowledge Base
- D4: Feedback DB
- D5: Classifications
- D6: Resolutions
- D7: Routing History
- D8: Agent Logs

Format: Two parallel horizontal lines with label between

**How to Create Data Store Symbol:**
1. Insert → Shape → Line (horizontal)
2. Duplicate line below
3. Group both lines
4. Add text label between them

**Data Flows:**
Connect all processes with arrows showing data movement

**Color Scheme:**
- P1: #667eea (blue)
- P2: #14b8a6 (teal)
- P3: #8b5cf6 (purple)
- P4: #f59e0b (amber)
- P5: #ef4444 (red)
- P6: #ec4899 (pink)
- P7: #10b981 (green)
- P8: #6366f1 (indigo)
- Data stores: #e5e7eb (gray)

---

## 📊 Entity Relationship Diagram - Basic (6 Categories)

### Entities to Create:

**Core Tables (main entities):**
1. tickets
2. ticket_embeddings
3. classifications
4. resolutions
5. resolution_feedback
6. llm_evaluations
7. routing_decisions
8. agent_conversations
9. agent_messages
10. users
11. departments
12. pii_detections

### Entity Format:
1. Insert → Shape → Rectangle
2. Divide into 3 sections (Header | Attributes | Keys)
3. Header: Table name (bold, colored background)
4. Attributes: List of columns with data types
5. Keys: PK/FK indicators

### Relationships:
1. Use "Connector" with crow's foot notation
2. Relationships:
   - tickets 1 → * ticket_embeddings
   - tickets 1 → * classifications
   - tickets 1 → * resolutions
   - resolutions 1 → 1 resolution_feedback
   - users * → 1 departments
   - etc.

### Crow's Foot Notation:
- One: Single line
- Many: Three-line fork (crow's foot)
- Optional: Circle on line
- Mandatory: Vertical line

### Colors:
- Entity headers: #667eea (blue)
- Primary keys: #f59e0b (amber)
- Foreign keys: #10b981 (green)

---

## 📋 Entity Relationship Diagram - Granular (24 Subcategories)

Same as Basic ERD, but add:

**Additional Tables:**
- categories (6 rows: Infrastructure, Application, Security, Database, Access Management, Network)
- subcategories (24 rows: 4 per category)

**Modified Relationships:**
- tickets * → 1 subcategories (instead of direct category string)
- subcategories * → 1 categories
- departments * → 1 categories

**Subcategories Table:**
```
id | category_id | name                        | description
---+-------------+-----------------------------+-------------
1  | 1           | Server & Compute            | ...
2  | 1           | Virtualization              | ...
3  | 1           | Container Orchestration     | ...
4  | 1           | Hardware & Datacenter       | ...
... (20 more)
```

---

## 🎨 Professional Styling Tips

### Fonts:
- Headers: Arial Bold, 12pt
- Body text: Arial, 10pt
- Annotations: Arial, 9pt

### Colors (consistent palette):
- Primary: #667eea (purple-blue)
- Secondary: #14b8a6 (teal)
- Accent: #f59e0b (amber)
- Success: #10b981 (green)
- Danger: #ef4444 (red)
- Neutral: #6b7280 (gray)

### Spacing:
- Between shapes: 40-60px
- Arrow labels: 10px from line
- Margin from page edge: 30px

### Line Styles:
- Data flows: Solid, 2pt, with arrows
- Optional: Dashed
- System boundaries: Dashed, 1pt

### Export Settings:
- Format: PNG
- DPI: 300
- Background: Transparent or White
- Include: Border (10px)

---

## 🚀 Quick Start Template

For fastest results, use Draw.io's built-in templates:

1. **For DFD:**
   - File → New → Software → Data Flow Diagram
   - Modify with our specific processes

2. **For ERD:**
   - File → New → Software → Entity Relationship
   - Use crow's foot notation
   - Add our specific entities

3. **For custom styling:**
   - Format → Style → Copy Style
   - Apply to multiple shapes at once

---

## ✅ Final Checklist

Before exporting:
- [ ] All text is legible
- [ ] Arrows point in correct direction
- [ ] Colors are consistent
- [ ] Spacing is uniform
- [ ] Labels don't overlap shapes
- [ ] Legend included (if complex)
- [ ] Page fits in A4 or Letter size

---

## 💡 Pro Tips

1. **Use Layers:** Separate background, shapes, text for easier editing
2. **Use Templates:** Save styled shapes as templates for reuse
3. **Use Grid Snap:** Enable for perfect alignment
4. **Use Distribution:** Select multiple shapes → Arrange → Distribute
5. **Use Copy Style:** Format one shape perfectly, then copy style to others

---

**Need the actual Draw.io files?**

I can create simplified versions, but the best approach is:
1. Use this guide to create them in Draw.io web app (15-20 minutes each)
2. You'll have full control over styling and layout
3. You can export to any format you need

Or alternatively, I can create a PowerPoint version with all diagrams that you can easily edit and convert!
