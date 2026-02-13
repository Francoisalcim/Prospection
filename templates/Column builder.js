/**
 * Column Builder - Drag and Drop functionality
 * Allows users to customize Excel export structure
 */

// Column definitions with all possible fields
const COLUMN_DEFINITIONS = {
  // Basic Info
  nct_id: { name: 'NCT ID', desc: 'Trial identifier', category: 'basic' },
  title: { name: 'Study Title', desc: 'Brief title of the study', category: 'basic' },
  status: { name: 'Status', desc: 'Overall study status', category: 'basic' },
  
  // Sponsors (always available)
  lead_sponsor: { name: 'Lead Sponsor', desc: 'Primary organization', category: 'sponsors', requires: 'sponsors' },
  lead_sponsor_type: { name: 'Sponsor Type', desc: 'Organization category', category: 'sponsors', requires: 'sponsors' },
  lead_sponsor_class: { name: 'Sponsor Class', desc: 'Industry/NIH/Other', category: 'sponsors', requires: 'sponsors' },
  collaborators: { name: 'Collaborators', desc: 'All collaborating organizations', category: 'sponsors', requires: 'sponsors' },
  collaborator_count: { name: 'Collaborator Count', desc: 'Number of collaborators', category: 'sponsors', requires: 'sponsors' },
  
  // Investigators
  principal_investigators: { name: 'Principal Investigators', desc: 'Lead researcher names', category: 'investigators', requires: 'investigators' },
  pi_affiliations: { name: 'PI Affiliations', desc: 'PI institutions', category: 'investigators', requires: 'investigators' },
  pi_count: { name: 'PI Count', desc: 'Number of PIs', category: 'investigators', requires: 'investigators' },
  
  // Locations
  facilities: { name: 'Facilities', desc: 'Hospital/clinic names', category: 'locations', requires: 'locations' },
  cities: { name: 'Cities', desc: 'Study locations', category: 'locations', requires: 'locations' },
  countries: { name: 'Countries', desc: 'Countries', category: 'locations', requires: 'locations' },
  location_count: { name: 'Location Count', desc: 'Number of sites', category: 'locations', requires: 'locations' },
  
  // Interventions
  drugs: { name: 'Drugs', desc: 'Medications tested', category: 'interventions', requires: 'interventions' },
  devices: { name: 'Devices', desc: 'Medical devices', category: 'interventions', requires: 'interventions' },
  procedures: { name: 'Procedures', desc: 'Surgical procedures', category: 'interventions', requires: 'interventions' },
  other_interventions: { name: 'Other Interventions', desc: 'Other types', category: 'interventions', requires: 'interventions' },
  intervention_count: { name: 'Intervention Count', desc: 'Total interventions', category: 'interventions', requires: 'interventions' },
  
  // Conditions
  conditions: { name: 'Conditions', desc: 'Diseases studied', category: 'conditions', requires: 'conditions' },
  keywords: { name: 'Keywords', desc: 'Study keywords', category: 'conditions', requires: 'conditions' },
  condition_count: { name: 'Condition Count', desc: 'Number of conditions', category: 'conditions', requires: 'conditions' },
  
  // Outcomes
  primary_outcomes: { name: 'Primary Outcomes', desc: 'Main endpoints', category: 'outcomes', requires: 'outcomes' },
  secondary_outcomes: { name: 'Secondary Outcomes', desc: 'Additional endpoints', category: 'outcomes', requires: 'outcomes' },
  primary_outcome_count: { name: 'Primary Outcome Count', desc: 'Number of primary', category: 'outcomes', requires: 'outcomes' },
  secondary_outcome_count: { name: 'Secondary Outcome Count', desc: 'Number of secondary', category: 'outcomes', requires: 'outcomes' },
  
  // Design
  phase: { name: 'Phase', desc: 'Study phase', category: 'design', requires: 'design' },
  study_type: { name: 'Study Type', desc: 'Interventional/Observational', category: 'design', requires: 'design' },
  enrollment: { name: 'Enrollment', desc: 'Number of participants', category: 'design', requires: 'design' },
  allocation: { name: 'Allocation', desc: 'Randomized/Non-randomized', category: 'design', requires: 'design' },
  intervention_model: { name: 'Intervention Model', desc: 'Parallel/Crossover/etc', category: 'design', requires: 'design' },
  primary_purpose: { name: 'Primary Purpose', desc: 'Treatment/Prevention/etc', category: 'design', requires: 'design' },
  masking: { name: 'Masking', desc: 'Blinding details', category: 'design', requires: 'design' },
  
  // Eligibility
  min_age: { name: 'Min Age', desc: 'Minimum age', category: 'eligibility', requires: 'eligibility' },
  max_age: { name: 'Max Age', desc: 'Maximum age', category: 'eligibility', requires: 'eligibility' },
  sex: { name: 'Sex', desc: 'Gender requirements', category: 'eligibility', requires: 'eligibility' },
  healthy_volunteers: { name: 'Healthy Volunteers', desc: 'Accepts healthy volunteers', category: 'eligibility', requires: 'eligibility' },
  eligibility_criteria: { name: 'Eligibility Criteria', desc: 'Full criteria text', category: 'eligibility', requires: 'eligibility' },
  
  // Contacts
  contact_name: { name: 'Contact Name', desc: 'Recruitment contact', category: 'contacts', requires: 'contacts' },
  contact_email: { name: 'Contact Email', desc: 'Email address', category: 'contacts', requires: 'contacts' },
  contact_phone: { name: 'Contact Phone', desc: 'Phone number', category: 'contacts', requires: 'contacts' },
  
  // Timeline
  start_date: { name: 'Start Date', desc: 'Study start date', category: 'timeline', requires: 'timeline' },
  completion_date: { name: 'Completion Date', desc: 'Expected completion', category: 'timeline', requires: 'timeline' },
  last_update: { name: 'Last Update', desc: 'Last modified date', category: 'timeline', requires: 'timeline' }
};

// Drag and drop state
let draggedElement = null;
let draggedFromPool = null;

/**
 * Create a column item element
 */
function createColumnItem(columnKey, showOrder = false, order = null) {
  const def = COLUMN_DEFINITIONS[columnKey];
  if (!def) return null;
  
  const item = document.createElement('div');
  item.className = 'column-item';
  item.draggable = true;
  item.dataset.columnKey = columnKey;
  
  const orderHtml = showOrder && order !== null 
    ? `<div class="column-item-order">${order}</div>` 
    : '';
  
  item.innerHTML = `
    ${orderHtml}
    <div class="column-item-info">
      <div class="column-item-name">${def.name}</div>
      <div class="column-item-desc">${def.desc}</div>
    </div>
    <div class="column-item-handle">⋮⋮</div>
  `;
  
  // Drag events
  item.addEventListener('dragstart', handleDragStart);
  item.addEventListener('dragend', handleDragEnd);
  item.addEventListener('dragover', handleDragOver);
  item.addEventListener('drop', handleDrop);
  item.addEventListener('dragleave', handleDragLeave);
  
  return item;
}

/**
 * Get available columns based on selected data extractions
 */
function getAvailableColumns() {
  const selectedExtractions = Array.from(
    document.querySelectorAll('#dataExtractGrid input[type="checkbox"]:checked')
  ).map(cb => cb.value);
  
  const available = [];
  
  // Always include basic fields
  available.push('nct_id', 'title', 'status');
  
  // Add fields based on selected extractions
  for (const [key, def] of Object.entries(COLUMN_DEFINITIONS)) {
    if (def.requires && selectedExtractions.includes(def.requires)) {
      available.push(key);
    }
  }
  
  return [...new Set(available)]; // Remove duplicates
}

/**
 * Update available columns pool
 */
function updateAvailableColumns() {
  const pool = document.getElementById('columnPool');
  const selected = document.getElementById('columnSelected');
  
  const availableColumns = getAvailableColumns();
  const selectedColumns = Array.from(selected.querySelectorAll('.column-item'))
    .map(item => item.dataset.columnKey);
  
  // Clear pool
  pool.innerHTML = '';
  
  // Add columns that are available but not selected
  const poolColumns = availableColumns.filter(col => !selectedColumns.includes(col));
  
  poolColumns.forEach(columnKey => {
    const item = createColumnItem(columnKey, false);
    if (item) pool.appendChild(item);
  });
  
  // Update counts
  updateCounts();
}

/**
 * Update column counts
 */
function updateCounts() {
  const poolCount = document.getElementById('columnPool').querySelectorAll('.column-item').length;
  const selectedCount = document.getElementById('columnSelected').querySelectorAll('.column-item').length;
  
  document.getElementById('poolCount').textContent = `${poolCount} column${poolCount !== 1 ? 's' : ''}`;
  document.getElementById('selectedCount').textContent = `${selectedCount} column${selectedCount !== 1 ? 's' : ''}`;
  
  updateSelectedColumnOrders();
}

/**
 * Update order numbers in selected columns
 */
function updateSelectedColumnOrders() {
  const selected = document.getElementById('columnSelected');
  const items = selected.querySelectorAll('.column-item');
  
  items.forEach((item, index) => {
    let orderEl = item.querySelector('.column-item-order');
    if (!orderEl) {
      orderEl = document.createElement('div');
      orderEl.className = 'column-item-order';
      item.insertBefore(orderEl, item.firstChild);
    }
    orderEl.textContent = index + 1;
  });
}

/**
 * Drag event handlers
 */
function handleDragStart(e) {
  draggedElement = this;
  draggedFromPool = this.parentElement.id === 'columnPool';
  
  this.classList.add('dragging');
  e.dataTransfer.effectAllowed = 'move';
  e.dataTransfer.setData('text/html', this.innerHTML);
}

function handleDragEnd(e) {
  this.classList.remove('dragging');
  
  // Remove drag-over class from all items
  document.querySelectorAll('.column-item').forEach(item => {
    item.classList.remove('drag-over');
  });
}

function handleDragOver(e) {
  if (e.preventDefault) {
    e.preventDefault();
  }
  
  e.dataTransfer.dropEffect = 'move';
  
  const target = e.target.closest('.column-item');
  if (target && target !== draggedElement) {
    target.classList.add('drag-over');
  }
  
  return false;
}

function handleDragLeave(e) {
  const target = e.target.closest('.column-item');
  if (target) {
    target.classList.remove('drag-over');
  }
}

function handleDrop(e) {
  if (e.stopPropagation) {
    e.stopPropagation();
  }
  
  e.target.classList.remove('drag-over');
  
  const dropTarget = e.target.closest('.column-item');
  const dropContainer = e.target.closest('.column-list');
  
  if (!draggedElement) return false;
  
  // Dropping into selected column list
  if (dropContainer && dropContainer.id === 'columnSelected') {
    if (dropTarget && dropTarget !== draggedElement) {
      // Insert before or after based on position
      const rect = dropTarget.getBoundingClientRect();
      const midpoint = rect.top + rect.height / 2;
      
      if (e.clientY < midpoint) {
        dropContainer.insertBefore(draggedElement, dropTarget);
      } else {
        dropContainer.insertBefore(draggedElement, dropTarget.nextSibling);
      }
    } else if (!dropTarget) {
      // Dropped in empty space - append to end
      dropContainer.appendChild(draggedElement);
    }
    
    // If came from pool, remove from pool, otherwise just reorder
    if (draggedFromPool) {
      // Already moved, just update pool
      updateAvailableColumns();
    }
  }
  // Dropping back into pool
  else if (dropContainer && dropContainer.id === 'columnPool') {
    // Remove from selected and update pool
    if (draggedElement.parentElement.id === 'columnSelected') {
      draggedElement.remove();
      updateAvailableColumns();
    }
  }
  
  updateCounts();
  
  return false;
}

// Also allow dropping on the container itself
document.getElementById('columnSelected').addEventListener('dragover', (e) => {
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';
});

document.getElementById('columnSelected').addEventListener('drop', (e) => {
  e.preventDefault();
  e.stopPropagation();
  
  const dropContainer = document.getElementById('columnSelected');
  
  if (draggedElement && !dropContainer.contains(draggedElement)) {
    dropContainer.appendChild(draggedElement);
    updateAvailableColumns();
    updateCounts();
  }
});

document.getElementById('columnPool').addEventListener('dragover', (e) => {
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';
});

document.getElementById('columnPool').addEventListener('drop', (e) => {
  e.preventDefault();
  e.stopPropagation();
  
  if (draggedElement && draggedElement.parentElement.id === 'columnSelected') {
    draggedElement.remove();
    updateAvailableColumns();
    updateCounts();
  }
});

/**
 * Button actions
 */
function clearAllColumns() {
  const selected = document.getElementById('columnSelected');
  selected.innerHTML = '';
  updateAvailableColumns();
  updateCounts();
}

function selectDefaultColumns() {
  clearAllColumns();
  
  const defaultColumns = [
    'nct_id',
    'title', 
    'status',
    'lead_sponsor',
    'phase',
    'conditions'
  ];
  
  const selected = document.getElementById('columnSelected');
  
  defaultColumns.forEach(columnKey => {
    if (COLUMN_DEFINITIONS[columnKey]) {
      const item = createColumnItem(columnKey, true);
      if (item) selected.appendChild(item);
    }
  });
  
  updateAvailableColumns();
  updateCounts();
}

function selectAllColumns() {
  clearAllColumns();
  
  const availableColumns = getAvailableColumns();
  const selected = document.getElementById('columnSelected');
  
  availableColumns.forEach(columnKey => {
    const item = createColumnItem(columnKey, true);
    if (item) selected.appendChild(item);
  });
  
  updateAvailableColumns();
  updateCounts();
}

/**
 * Get selected columns in order
 */
function getSelectedColumns() {
  const selected = document.getElementById('columnSelected');
  return Array.from(selected.querySelectorAll('.column-item'))
    .map(item => item.dataset.columnKey);
}

// Export functions to global scope
window.clearAllColumns = clearAllColumns;
window.selectDefaultColumns = selectDefaultColumns;
window.selectAllColumns = selectAllColumns;
window.getSelectedColumns = getSelectedColumns;
window.updateAvailableColumns = updateAvailableColumns;