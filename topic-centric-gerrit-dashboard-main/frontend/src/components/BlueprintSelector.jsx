import { useEffect, useState, useMemo } from "react";

export default function BlueprintSelector({ onSelect, selectedId }) {
  const [blueprints, setBlueprints] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedProject, setSelectedProject] = useState("ALL");

  useEffect(() => {
    fetch("http://localhost:3001/api/blueprints")
      .then((res) => res.json())
      .then((data) => {
        setBlueprints(data.blueprints || []);
        setLoading(false);
      })
      .catch((err) => {
        console.error("Failed to fetch blueprints", err);
        setLoading(false);
      });
  }, []);

  // Extract unique projects for project quick filter
  const projects = useMemo(() => {
    const set = new Set();
    blueprints.forEach(b => {
      if (b.project) set.add(b.project);
    });
    return Array.from(set).sort();
  }, [blueprints]);

  // Filter blueprints in real-time by search query and project
  const filteredBlueprints = useMemo(() => {
    let list = blueprints;
    
    if (selectedProject !== "ALL") {
      list = list.filter(b => b.project === selectedProject);
    }
    
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase().trim();
      list = list.filter(b => 
        (b.name && b.name.toLowerCase().includes(q)) ||
        (b.title && b.title.toLowerCase().includes(q)) ||
        (b.project && b.project.toLowerCase().includes(q)) ||
        (b.id && b.id.toLowerCase().includes(q))
      );
    }
    
    return list;
  }, [blueprints, searchQuery, selectedProject]);

  const handleClearSearch = () => {
    setSearchQuery("");
    setSelectedProject("ALL");
  };

  return (
    <div className="card blueprintSelectorCard">
      <div className="selectorHeaderRow">
        <div>
          <div className="sectionTitle">Select Blueprint</div>
          <div className="sectionSubtitle">
            Search across {blueprints.length.toLocaleString()} OpenStack specifications & blueprint models
          </div>
        </div>
        
        {/* Active count badge */}
        <div className="selectorCountBadge">
          {loading ? (
            "Loading blueprints..."
          ) : searchQuery.trim() || selectedProject !== "ALL" ? (
            `Showing ${filteredBlueprints.length} of ${blueprints.length}`
          ) : (
            `${blueprints.length} blueprints available`
          )}
        </div>
      </div>

      <div className="selectorControlsRow">
        {/* Search Input with Icon & Clear button */}
        <div className="selectorSearchBox">
          <span className="searchIcon">🔍</span>
          <input
            type="text"
            className="selectorSearchInput"
            placeholder="Search by blueprint name, title, or project (e.g. xenapi, migration, nova)..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            disabled={loading}
          />
          {searchQuery && (
            <button 
              className="searchClearBtn" 
              onClick={() => setSearchQuery("")} 
              title="Clear search"
            >
              ✕
            </button>
          )}
        </div>

        {/* Project Filter Select */}
        <div className="projectFilterWrapper">
          <select 
            className="projectFilterSelect"
            value={selectedProject}
            onChange={(e) => setSelectedProject(e.target.value)}
            disabled={loading}
          >
            <option value="ALL">All Projects ({projects.length})</option>
            {projects.map(p => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Main Blueprint Dropdown Selector */}
      <div className="selectorDropdownWrapper">
        <select
          className="blueprintSelect"
          value={selectedId || ""}
          onChange={(e) => onSelect(e.target.value)}
          disabled={loading || filteredBlueprints.length === 0}
        >
          <option value="" disabled>
            {loading 
              ? "Loading blueprints..." 
              : filteredBlueprints.length === 0 
                ? "No blueprints match your search" 
                : "Choose a blueprint from list..."}
          </option>
          {filteredBlueprints.map((bp) => (
            <option key={bp.id} value={bp.id}>
              {bp.name} — {bp.title} [{bp.project}]
            </option>
          ))}
        </select>
      </div>

      {/* Quick matching tags when searching */}
      {searchQuery.trim() && filteredBlueprints.length > 0 && filteredBlueprints.length <= 8 && (
        <div className="quickMatchesRow">
          <span className="quickMatchesLabel">Quick Select:</span>
          <div className="quickMatchesPills">
            {filteredBlueprints.map(bp => (
              <button 
                key={bp.id}
                className={`quickMatchPill ${selectedId === bp.id ? 'active' : ''}`}
                onClick={() => onSelect(bp.id)}
              >
                <span className="pillProject">{bp.project}/</span>
                <span className="pillName">{bp.name}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
