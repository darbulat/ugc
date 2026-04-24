# Obsidian Vault Setup

This project is configured as an **Obsidian Vault** for collaborative knowledge management and documentation.

## What is an Obsidian Vault?

Obsidian is a knowledge management app that works with markdown files in a local folder (vault). It provides:
- **Backlinks** — See what documents reference each other
- **Graph view** — Visualize relationships as a network
- **Search** — Full-text search across all documents
- **Templates** — Quick document creation with predefined structure
- **Outlines** — Navigate documents by headings
- **Sync** — Optional cloud sync (not configured here)

## Getting Started

### 1. Open the Vault in Obsidian

1. **Download Obsidian** from [obsidian.md](https://obsidian.md) if you haven't
2. **Open the vault:**
   - Launch Obsidian
   - Click "Open vault as folder"
   - Navigate to `/home/user/ugc/` and select it
   - Obsidian will scan and index all markdown files

### 2. Explore the Documentation

Start with **`INDEX.md`** — it's the hub for navigating all documentation.

**Key sections to explore:**
- [[docs/1-ARCHITECTURE.md|Architecture Overview]] — System design and layers
- [[docs/2-DOMAIN-MODEL.md|Domain Model]] — Entities and business rules
- [[docs/3-DEVELOPMENT-WORKFLOW.md|Development Workflow]] — How to develop
- [[docs/4-INFRASTRUCTURE.md|Infrastructure]] — Services and deployment
- [[docs/5-PATTERNS.md|Design Patterns]] — Key architectural patterns
- [[docs/GLOSSARY.md|Glossary]] — Terminology and definitions
- [[docs/QUICK-REFERENCE.md|Quick Reference]] — Commands and common tasks

### 3. Use Obsidian Features

#### Graph View
Shows connections between documents as a network:
- **Keyboard:** Ctrl+G (Cmd+G on Mac)
- **What it shows:** Every internal link creates a connection
- **Use case:** Understand how concepts relate
- **Filters:** Filter by document type or tag

#### Search
Full-text search across all documents:
- **Keyboard:** Ctrl+Shift+F (Cmd+Shift+F on Mac)
- **Filters:** `tag:` (find by tag), `path:` (find in folder)
- **Examples:**
  - `tag:architecture` — Find all architecture docs
  - `path:docs/` — Search only in docs folder
  - `Repository pattern` — Search by keyword

#### Backlinks
See what documents reference the current document:
- **Panel:** Right sidebar
- **Use case:** Discover related documents you might have missed
- **Collapsed sections:** Click to expand

#### Outgoing Links
See what documents the current document references:
- **Panel:** Right sidebar
- **Use case:** Follow topics deeper

#### Tags
Browse and filter documents by tags:
- **Panel:** Right sidebar (tag icon)
- **Common tags:**
  - `architecture` — Architectural decisions
  - `workflow` — Process documentation
  - `guide` — How-to guides
  - `reference` — Reference materials
  - `core` — Core system documentation

#### Templates
Create new documents from templates:
- **Location:** `.obsidian/templates/`
- **Available templates:**
  - Feature Plan
  - Architecture Document
  - API Documentation
  - Decision Log (ADR)

**How to use:**
1. Create new note (Ctrl+N)
2. Type template name in frontmatter or use command palette
3. Fill in placeholders ({{like this}})

---

## Vault Structure

```
ugc/
├── INDEX.md                    # Main hub - START HERE!
├── OBSIDIAN-VAULT-SETUP.md     # This file
├── .obsidian/                  # Obsidian configuration
│   ├── app.json               # Editor settings
│   ├── core-plugins.json      # Enabled plugins
│   ├── workspace.json         # Layout & state
│   ├── templates/             # Document templates
│   │   ├── Feature Plan Template.md
│   │   ├── Architecture Document Template.md
│   │   ├── API Documentation Template.md
│   │   └── Decision Log Template.md
│   └── snippets/              # Custom CSS (optional)
└── docs/
    ├── 1-ARCHITECTURE.md      # System design
    ├── 2-DOMAIN-MODEL.md      # Entities & enums
    ├── 3-DEVELOPMENT-WORKFLOW.md  # Dev guide
    ├── 4-INFRASTRUCTURE.md    # Services & deployment
    ├── 5-PATTERNS.md          # Design patterns
    ├── GLOSSARY.md            # Terminology
    ├── QUICK-REFERENCE.md     # Commands & cheatsheet
    └── ... (other docs)
```

---

## Tips & Tricks

### Navigation
- **Follow links:** Ctrl+click (Cmd+click) to open in new pane
- **Back button:** Alt+Left (Cmd+Left) to go back
- **Quick open:** Ctrl+O (Cmd+O) to search and open any file

### Writing
- **Internal links:** `[[Document Name]]` creates a link (autocomplete with Ctrl+Space)
- **Alias:** `[[file.md|Display Name]]` — link text different from filename
- **Headings:** Use `#`, `##`, `###` for hierarchy (outline view shows these)
- **Code blocks:** Use ` ```python ` for syntax highlighting

### Productivity
- **Table of contents:** Create with `[[_TOC_]]` or use outline view
- **Embed documents:** `![[file.md]]` to include another document's content
- **Daily notes:** Use built-in daily notes (optional)
- **Starred documents:** Pin frequently accessed docs (star icon in header)

### Searching Effectively
```
# Find all service-related docs
tag:service

# Find in application layer
path:application

# Find architectural decisions
Repository pattern

# Combine: find core architecture docs
tag:core path:docs
```

---

## Collaboration Tips

### Sharing with Team
1. **Clone the repo** — Team members clone the git repo
2. **Open in Obsidian** — Each person opens the same vault folder
3. **Pull changes** — `git pull` to get latest docs
4. **Commit docs** — Changes are tracked in git

### Adding New Documentation

1. **Create document:**
   - Use a template from `.obsidian/templates/`
   - Name it descriptively (e.g., `User Authentication Flow.md`)
   - Add appropriate tags and metadata

2. **Link to related docs:**
   - Use `[[Document Name]]` to create internal links
   - Backlinks will show automatically
   - Graph view will visualize connections

3. **Update INDEX.md:**
   - Add link to new document in appropriate section
   - Keep index organized by category

4. **Commit to git:**
   ```bash
   git add docs/your-document.md
   git commit -m "docs: add documentation about X"
   git push
   ```

---

## Keyboard Shortcuts

| Action | Windows/Linux | Mac |
|--------|---|---|
| **Search** | Ctrl+Shift+F | Cmd+Shift+F |
| **Graph View** | Ctrl+G | Cmd+G |
| **Open File** | Ctrl+O | Cmd+O |
| **Create Note** | Ctrl+N | Cmd+N |
| **Command Palette** | Ctrl+P | Cmd+P |
| **Link Suggestion** | Ctrl+Space | Cmd+Space |
| **Toggle Sidebar** | Ctrl+B | Cmd+B |
| **Back** | Alt+Left | Cmd+Left |
| **Forward** | Alt+Right | Cmd+Right |
| **Embed File** | Type `![[` | Type `![[` |

---

## Customization

### Change Theme
1. **Settings** → Appearance
2. Choose theme (Light, Dark, System)
3. Optional: Download community themes

### Custom CSS
Add custom styles in `.obsidian/snippets/custom.css`:
```css
/* Make h1 bigger */
.markdown-preview-view h1 {
  font-size: 2em;
}

/* Highlight internal links */
.internal-link {
  color: #0066cc;
  font-weight: bold;
}
```

### Enable/Disable Plugins
1. **Settings** → Community Plugins
2. Browse and install (or disable built-in plugins)
3. Recommended plugins:
   - **Dataview** — Query and display data from documents
   - **Calendar** — Calendar view for daily notes
   - **Recent Files** — Quick access to recent documents

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| **Can't open vault** | Ensure you're selecting the `/ugc` folder, not a subfolder |
| **Backlinks not showing** | Ensure files use `[[internal-link]]` format |
| **Graph view empty** | Graph shows only documents with links; add links to connect docs |
| **Search not working** | Wait for indexing to complete (see bottom status bar) |
| **Template not appearing** | Ensure template files are in `.obsidian/templates/` |

---

## Next Steps

1. **Open Obsidian** and explore the vault
2. **Read INDEX.md** to understand the structure
3. **Use Graph View** (Ctrl+G) to visualize relationships
4. **Search** (Ctrl+Shift+F) for specific topics
5. **Create a new doc** using a template when ready
6. **Share with team** — They can clone the repo and open the same vault

---

## Related Documents
- [[INDEX.md|Main Index]]
- [[docs/QUICK-REFERENCE.md|Quick Reference]]
- [[docs/GLOSSARY.md|Glossary]]

---

**Happy documenting!** 📚
