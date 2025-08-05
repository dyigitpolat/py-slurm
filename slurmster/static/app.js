// slurmster dashboard front-end

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error(await res.text());
  if (res.status === 204) return null;
  return res.json();
}

// ---------------------------------------------------------------------------
// Sorting helpers
// ---------------------------------------------------------------------------
let sortKey = 'job_id';
let sortDir = 'desc';
let cachedJobs = [];
let paramKeysGlobal = [];

// helper to compute param keys union
function computeParamKeys(jobs){
  const set=new Set();jobs.forEach(j=>Object.keys(j.params||{}).forEach(k=>set.add(k)));return [...set];}

function valueForSort(job, key) {
  if (key in job) return job[key];
  return job.params ? job.params[key] : undefined;
}

function compareJobs(a, b) {
  const dir = sortDir === 'asc' ? 1 : -1;
  const va = valueForSort(a, sortKey);
  const vb = valueForSort(b, sortKey);
  if (va === undefined) return 1 * dir;
  if (vb === undefined) return -1 * dir;
  const na = parseFloat(va);
  const nb = parseFloat(vb);
  const num = !isNaN(na) && !isNaN(nb);
  if (num) return (na - nb) * dir;
  return String(va).localeCompare(String(vb)) * dir;
}

// ---------------------------------------------------------------------------
// Table building
// ---------------------------------------------------------------------------
function buildTableHead(paramKeys) {
  const head = document.getElementById('table-head');
  head.innerHTML = '';
  const tr = document.createElement('tr');
  const columns = ['job_id', 'state', ...paramKeys.sort()];
  const pretty = {job_id: 'Job ID', state: 'State'};
  columns.forEach(col => {
    const th = document.createElement('th');
    th.className = 'px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer select-none';
    th.innerHTML = `${pretty[col] || col} ${(sortKey===col?(sortDir==='asc'?'&uarr;':'&darr;'):'')}`;
    th.onclick = () => {
      if (sortKey === col) sortDir = sortDir === 'asc' ? 'desc' : 'asc';
      else { sortKey = col; sortDir = 'asc'; }
      renderJobs();
    };
    tr.appendChild(th);
  });
  tr.appendChild(Object.assign(document.createElement('th'), {className: 'px-6 py-3'}));
  head.appendChild(tr);
}

function stateBadge(st, fetched = false) {
  const map = {RUNNING:'blue',PENDING:'yellow',FINISHED:'green',CANCELLED:'red'};
  const color = map[st] || 'gray';
  const fetchedIndicator = fetched ? ' <span class="inline-flex px-1 text-xs font-semibold rounded bg-purple-100 text-purple-800">📁</span>' : '';
  return `<span class="inline-flex px-2 text-xs font-semibold rounded-full bg-${color}-100 text-${color}-800">${st}</span>${fetchedIndicator}`;
}

function actionButtons(job) {
  // Cancel button - only enabled for PENDING and RUNNING jobs
  const canCancel = ['PENDING', 'RUNNING'].includes(job.state);
  const cancelClass = canCancel 
    ? 'px-3 py-1 bg-red-600 hover:bg-red-700 text-white rounded-md cursor-pointer'
    : 'px-3 py-1 bg-gray-400 text-gray-200 rounded-md cursor-not-allowed';
  const cancelClick = canCancel ? `onclick="cancelJob('${job.job_id}')"` : '';
  const cancel = `<button ${cancelClick} class="${cancelClass}" ${canCancel ? '' : 'disabled'}>Cancel</button>`;

  // Monitor button - always enabled if job_id exists
  const monitor = job.job_id 
    ? `<button onclick="monitorJob('${job.job_id}')" class="ml-2 px-3 py-1 bg-blue-600 hover:bg-blue-700 text-white rounded-md">Monitor</button>` 
    : `<button class="ml-2 px-3 py-1 bg-gray-400 text-gray-200 rounded-md cursor-not-allowed" disabled>Monitor</button>`;

  // Fetch button - always enabled if job_id exists
  const canFetch = !!job.job_id;
  const fetchClass = canFetch
    ? 'ml-2 px-3 py-1 bg-yellow-600 hover:bg-yellow-700 text-white rounded-md cursor-pointer'
    : 'ml-2 px-3 py-1 bg-gray-400 text-gray-200 rounded-md cursor-not-allowed';
  const fetchClick = canFetch ? `onclick="fetchJob('${job.job_id}')"` : '';
  const fetchTitle = job.fetched ? 'Re-fetch files' : 'Fetch job files';
  const fetch = `<button ${fetchClick} class="${fetchClass}" ${canFetch ? '' : 'disabled'} title="${fetchTitle}">Fetch</button>`;

  // Browse button - enabled if run_dir exists
  const canBrowse = !!job.run_dir;
  const browseClass = canBrowse
    ? 'ml-2 px-3 py-1 bg-green-600 hover:bg-green-700 text-white rounded-md cursor-pointer'
    : 'ml-2 px-3 py-1 bg-gray-400 text-gray-200 rounded-md cursor-not-allowed';
  const browseClick = canBrowse ? `onclick="browseJob('${job.job_id}')"` : '';
  const browseTitle = !canBrowse ? 'No run directory available' : '';
  const browse = `<button ${browseClick} class="${browseClass}" ${canBrowse ? '' : 'disabled'} title="${browseTitle}">Browse</button>`;

  return cancel + monitor + fetch + browse;
}

function renderJobs(){
  const paramKeys=paramKeysGlobal;
  buildTableHead(paramKeys);
  const jobs=[...cachedJobs].sort(compareJobs);
  const tbody=document.getElementById('jobs-tbody');
  tbody.innerHTML='';
  jobs.forEach(j=>{
    const tr=document.createElement('tr');
    const cells=[];
    cells.push(`<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">${j.job_id||'-'}</td>`);
    cells.push(`<td class="px-6 py-4 whitespace-nowrap text-sm">${stateBadge(j.state, j.fetched)}</td>`);
    paramKeys.sort().forEach(k=>cells.push(`<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">${j.params?.[k]??'-'}</td>`));
    cells.push(`<td class="px-6 py-4 whitespace-nowrap text-right text-sm font-medium flex flex-row justify-end">${actionButtons(j)}</td>`);
    tr.innerHTML=cells.join('');
    tbody.appendChild(tr);
  });
}

async function refreshJobs(showLoading = false){
  if (showLoading) {
    showJobsLoading();
  }
  try {
  const jobs=await api('/api/jobs');
  cachedJobs=jobs;
  paramKeysGlobal=computeParamKeys(jobs);
  renderJobs();
  } catch (error) {
    showJobsError(error.message);
  } finally {
    hideJobsLoading();
  }
}

async function cancelJob(jid){
  // Find the cancel button and show loading state
  const cancelButtons = document.querySelectorAll(`button[onclick="cancelJob('${jid}')"]`);
  cancelButtons.forEach(btn => {
    btn.disabled = true;
    btn.innerHTML = '<svg class="animate-spin -ml-1 mr-2 h-4 w-4 text-white inline" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>Canceling...';
    btn.classList.add('opacity-75', 'cursor-not-allowed');
  });

  try {
    await api(`/api/jobs/${jid}/cancel`,{method:'POST'});
    refreshJobs(false);
  } catch (error) {
    alert(`❌ Failed to cancel job ${jid}: ${error.message}`);
    // Restore button state on error
    cancelButtons.forEach(btn => {
      btn.disabled = false;
      btn.textContent = 'Cancel';
      btn.classList.remove('opacity-75', 'cursor-not-allowed');
    });
  }
}

async function fetchJob(jobId){
  // Find the fetch button and show loading state
  const fetchButtons = document.querySelectorAll(`button[onclick="fetchJob('${jobId}')"]`);
  fetchButtons.forEach(btn => {
    btn.disabled = true;
    btn.innerHTML = '<svg class="animate-spin -ml-1 mr-2 h-4 w-4 text-white inline" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>Fetching...';
    btn.classList.add('opacity-75', 'cursor-not-allowed');
  });

  try {
    await api(`/api/jobs/${jobId}/fetch`,{method:'POST'});
    
    // Immediately hide fetch button and show fetched indicator for instant feedback
    fetchButtons.forEach(btn => btn.style.display = 'none');
    
    // Find the job's state cell and add folder icon immediately
    const jobRows = document.querySelectorAll('#jobs-tbody tr');
    jobRows.forEach(row => {
      const cells = row.querySelectorAll('td');
      if (cells.length > 0) {
        // Check if this is the right job by looking for the job_id in the actions
        const actionsCell = cells[cells.length - 1];
        if (actionsCell.innerHTML.includes(`fetchJob('${jobId}')`)) {
          const stateCell = cells[1]; // State is typically the second column
          const existingBadge = stateCell.innerHTML;
          if (!existingBadge.includes('📁')) {
            stateCell.innerHTML = existingBadge + ' <span class="inline-flex px-1 text-xs font-semibold rounded bg-purple-100 text-purple-800">📁</span>';
          }
        }
      }
    });
    
    alert(`✅ Successfully fetched outputs for job ${jobId}. Files downloaded to local workspace.`);
    
    // Refresh jobs to get the updated data from server
    setTimeout(() => refreshJobs(false), 100);
  } catch (error) {
    alert(`❌ Failed to fetch job ${jobId}: ${error.message}`);
    // Restore button state on error
    fetchButtons.forEach(btn => {
      btn.disabled = false;
      btn.textContent = 'Fetch';
      btn.classList.remove('opacity-75', 'cursor-not-allowed');
      btn.style.display = '';
    });
  }
}

async function fetchAllFinished(){
  setButtonLoading('fetch-all', true, 'Fetching All...');
  try {
    await api('/api/jobs/fetch-all',{method:'POST'});
    alert('✅ Successfully fetched all finished job outputs to local workspace.');
    refreshJobs(false);
  } catch (error) {
    alert(`❌ Failed to fetch all jobs: ${error.message}`);
  } finally {
    setButtonLoading('fetch-all', false);
  }
}

// ---------------------------------------------------------------------------
// File browser functionality
// ---------------------------------------------------------------------------
let currentBrowsePath = '';
let currentBrowseJobId = '';

async function browseJob(jobId) {
  // Store the current job_id for browsing
  currentBrowseJobId = jobId;
  
  // Show browse modal  
  document.getElementById('browse-modal').classList.remove('hidden');
  
  // Load root directory
  await loadDirectory('');
}

async function loadDirectory(path) {
  currentBrowsePath = path;
  
  const loading = document.getElementById('browse-loading');
  const pathDisplay = document.getElementById('browse-path');
  const upButton = document.getElementById('browse-up');
  const filesTable = document.getElementById('browse-files');
  const emptyDiv = document.getElementById('browse-empty');
  const errorDiv = document.getElementById('browse-error');
  
  // Show loading state
  loading.classList.remove('hidden');
  emptyDiv.classList.add('hidden');
  errorDiv.classList.add('hidden');
  
  // Update path display
  pathDisplay.textContent = path || '/';
  
  // Enable/disable up button
  upButton.disabled = !path;
  
  try {
    const params = new URLSearchParams();
    if (path) params.append('path', path);
    
    const response = await api(`/api/jobs/${currentBrowseJobId}/browse?${params}`);
    
    if (response.error) {
      throw new Error(response.error);
    }
    
    filesTable.innerHTML = '';
    
    if (response.files.length === 0) {
      emptyDiv.classList.remove('hidden');
    } else {
      response.files.forEach(file => {
        const row = document.createElement('tr');
        row.className = 'hover:bg-gray-50';
        
        const icon = file.is_directory ? '📁' : '📄';
        const clickHandler = file.is_directory ? `onclick="loadDirectory('${path ? path + '/' : ''}${file.name}')"` : '';
        const cursor = file.is_directory ? 'cursor-pointer' : '';
        
        row.innerHTML = `
          <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900 ${cursor}" ${clickHandler}>
            ${icon} ${file.name}
          </td>
          <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">${file.size}</td>
          <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">${file.date}</td>
          <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">${file.permissions}</td>
        `;
        
        filesTable.appendChild(row);
      });
    }
  } catch (error) {
    errorDiv.textContent = error.message;
    errorDiv.classList.remove('hidden');
  } finally {
    loading.classList.add('hidden');
  }
}

async function navigateToDir(dirName) {
  const newPath = currentBrowsePath ? `${currentBrowsePath}/${dirName}` : dirName;
  await loadDirectory(newPath);
}

async function navigateUp() {
  if (!currentBrowsePath) return;
  
  const parts = currentBrowsePath.split('/');
  parts.pop();
  const newPath = parts.join('/');
  
  await loadDirectory(newPath);
}

async function downloadFile(fileName) {
  try {
    const filePath = currentBrowsePath ? `${currentBrowsePath}/${fileName}` : fileName;
    const params = new URLSearchParams();
    params.append('file_path', filePath);
    
    // Create a temporary link to trigger download
    const link = document.createElement('a');
    link.href = `/api/jobs/${currentBrowseJobId}/download?${params}`;
    link.download = fileName;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    
  } catch (error) {
    alert(`Failed to download ${fileName}: ${error.message}`);
  }
}

function closeBrowseModal() {
  const modal = document.getElementById('browse-modal');
  modal.classList.add('hidden');
  modal.classList.remove('flex');
  currentBrowseJobId = '';
  currentBrowsePath = '';
}

// ---------------------------------------------------------------------------
// Loading states
// ---------------------------------------------------------------------------
function showJobsLoading() {
  const tbody = document.getElementById('jobs-tbody');
  tbody.innerHTML = '<tr><td colspan="100%" class="px-6 py-8 text-center text-gray-500"><div class="flex items-center justify-center"><svg class="animate-spin -ml-1 mr-3 h-5 w-5 text-gray-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>Loading jobs...</div></td></tr>';
}

function hideJobsLoading() {
  // This will be handled by renderJobs() which replaces the tbody content
}

function showJobsError(message) {
  const tbody = document.getElementById('jobs-tbody');
  tbody.innerHTML = `<tr><td colspan="100%" class="px-6 py-8 text-center text-red-500">Error loading jobs: ${message}</td></tr>`;
}

function setButtonLoading(buttonId, isLoading, loadingText = 'Loading...') {
  const button = document.getElementById(buttonId);
  if (!button) return;
  
  if (isLoading) {
    button.disabled = true;
    button.dataset.originalText = button.textContent;
    button.innerHTML = `<svg class="animate-spin -ml-1 mr-2 h-4 w-4 text-white inline" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>${loadingText}`;
    button.classList.add('opacity-75', 'cursor-not-allowed');
  } else {
    button.disabled = false;
    button.textContent = button.dataset.originalText || button.textContent;
    button.classList.remove('opacity-75', 'cursor-not-allowed');
  }
}

// ---------------------------------------------------------------------------
// Log monitoring
// ---------------------------------------------------------------------------
let ws=null;function monitorJob(jobId){const modal=document.getElementById('log-modal');const title=document.getElementById('log-title');const content=document.getElementById('log-content');title.textContent=`Logs for Job ${jobId}`;content.textContent='';modal.classList.remove('hidden');modal.classList.add('flex');const wsUrl=`${location.origin.replace(/^http/,'ws')}/ws/logs/${jobId}`;ws=new WebSocket(wsUrl);ws.onmessage=e=>{content.textContent+=e.data+'\n';content.scrollTop=content.scrollHeight;};ws.onclose=()=>console.log('ws closed');}
function closeLogModal(){document.getElementById('log-modal').classList.add('hidden');document.getElementById('log-modal').classList.remove('flex');if(ws){ws.close();ws=null;}}
document.getElementById('close-modal').addEventListener('click',closeLogModal);

// Browse modal event listeners
document.getElementById('close-browse-modal').addEventListener('click',closeBrowseModal);
document.getElementById('browse-up').addEventListener('click',navigateUp);
document.getElementById('browse-refresh').addEventListener('click',()=>loadDirectory(currentBrowsePath));

// ---------------------------------------------------------------------------
// Config Panels
// ---------------------------------------------------------------------------
async function buildConfigPanels(){
  const cfg=await api('/api/config');
  const fullCfg=await api('/api/config/full'); // Get full config including remote, files, slurm
  const area=document.getElementById('config-area');
  area.innerHTML='';
  
  // Helpers
  const createInput=(id,val='',placeholder='')=>`<input id="${id}" class="input-field" value="${val}" placeholder="${placeholder}"/>`;
  const createTextarea=(id,val='',placeholder='',rows=3)=>`<div class="code-wrapper"><pre id="${id}-pre"></pre><textarea id="${id}" class="input-field code-field" rows="${rows}" placeholder="${placeholder}">${val}</textarea></div>`;
  
  // Determine param keys
  const grid=cfg.grid||{};const exp=(cfg.experiments&&cfg.experiments[0])||{};const keys=Array.from(new Set([...Object.keys(grid),...Object.keys(exp)]));
  
  // Tutorial panel
  const tutorial=document.createElement('div');tutorial.className='bg-blue-50 border border-blue-200 rounded shadow p-4 mb-4 col-span-2';
  tutorial.innerHTML=`
    <div class="flex items-center justify-between">
      <h3 class="text-lg font-semibold text-blue-800 mb-2">📚 Tutorial: Configuration & Placeholders</h3>
      <button id="toggle-tutorial" class="text-blue-600 hover:text-blue-800 text-sm underline">Hide</button>
    </div>
    <div id="tutorial-content">
      <div class="text-sm text-blue-700 space-y-2">
        <p><strong>Available Placeholders:</strong></p>
        <ul class="list-disc list-inside ml-4 space-y-1">
          <li><code class="bg-blue-100 px-1 rounded">{base_dir}</code> - Remote base directory (e.g. /home/user/experiments)</li>
          <li><code class="bg-blue-100 px-1 rounded">{remote_dir}</code> - Same as base_dir</li>
          <li><code class="bg-blue-100 px-1 rounded">{run_dir}</code> - Per-run directory (base_dir/runs/exp_name)</li>
          <li><code class="bg-blue-100 px-1 rounded">{parameter_name}</code> - Any parameter you define (e.g. {lr}, {epochs})</li>
        </ul>
        <p><strong>Example Run Command:</strong></p>
        <code class="block bg-blue-100 p-2 rounded text-xs">
source venv/bin/activate<br>
python train.py --lr {lr} --epochs {epochs} --save_model "{run_dir}/model.pth"
        </code>
        <p><strong>Files:</strong> Use relative paths. Push files are uploaded before job starts. Fetch files are downloaded after completion.</p>
      </div>
    </div>
  `;
  area.appendChild(tutorial);
  
  // Configuration panel (left half)
  const configPanel=document.createElement('div');configPanel.className='bg-white rounded shadow p-4';
  configPanel.innerHTML=`
    <h3 class="text-lg font-semibold mb-3">🔧 Configuration</h3>
    <div class="space-y-4">
      <div>
        <label class="text-sm font-medium text-gray-700">Base Directory (Remote)</label>
        ${createTextarea('base-dir', fullCfg.remote?.base_dir || '', '~/experiments or {remote_dir}/subdir', 1)}
      </div>
      <div>
        <label class="text-sm font-medium text-gray-700">Files to Push (comma separated)</label>
        ${createTextarea('files-push', (fullCfg.files?.push || []).join(', '), 'train.py, requirements.txt, {run_dir}/config.json', 2)}
      </div>
      <div>
        <label class="text-sm font-medium text-gray-700">Files to Fetch (comma separated)</label>
        ${createTextarea('files-fetch', (fullCfg.files?.fetch || []).join(', '), '{run_dir}/model.pth, {run_dir}/log.txt', 2)}
      </div>
      <div>
        <label class="text-sm font-medium text-gray-700">SLURM Directives</label>
        ${createTextarea('slurm-directives', fullCfg.slurm?.directives || '', '#SBATCH --job-name={base_dir}\\n#SBATCH --partition=gpu\\n#SBATCH --time=00:10:00', 6)}
      </div>
      <div>
        <label class="text-sm font-medium text-gray-700">Environment Setup Script</label>
        ${createTextarea('env-setup', cfg.env_setup || '', 'env_setup.sh (optional)', 2)}
      </div>
      <div>
        <label class="text-sm font-medium text-gray-700">Run Command</label>
        ${createTextarea('run-command', cfg.command || '', 'source venv/bin/activate\\npython train.py --lr {lr}', 4)}
      </div>
    </div>
  `;
  area.appendChild(configPanel);
  
  // Job submission container (right half)
  const jobContainer=document.createElement('div');jobContainer.className='space-y-4';
  
  // Single job submission panel
  const singlePanel=document.createElement('div');singlePanel.className='bg-white rounded shadow p-4';
  singlePanel.innerHTML=`
    <h3 class="text-lg font-semibold mb-3">🎯 Single Job Submission</h3>
    <div class="space-y-3">
      <div id="single-fields" class="grid grid-cols-1 md:grid-cols-2 gap-3"></div>
      <div class="flex items-center space-x-2">
        <input id="single-new-param" placeholder="add new parameter" class="input-field flex-1"/>
        <button id="single-add-param" class="px-3 py-2 bg-slate-600 hover:bg-slate-700 text-white rounded text-sm">Add</button>
      </div>
      <button id="single-submit" class="px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded">Submit Single Job</button>
    </div>
  `;
  jobContainer.appendChild(singlePanel);
  
  // Grid job submission panel  
  const gridPanel=document.createElement('div');gridPanel.className='bg-white rounded shadow p-4';
  gridPanel.innerHTML=`
    <h3 class="text-lg font-semibold mb-3">🔥 Grid Job Submission</h3>
    <div class="space-y-3">
      <div id="grid-fields" class="grid grid-cols-1 md:grid-cols-2 gap-3"></div>
      <div class="flex items-center space-x-2">
        <input id="grid-new-param" placeholder="add new parameter" class="input-field flex-1"/>
        <button id="grid-add-param" class="px-3 py-2 bg-slate-600 hover:bg-slate-700 text-white rounded text-sm">Add</button>
      </div>
      <button id="grid-submit" class="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded">Submit Grid Jobs</button>
    </div>
  `;
  jobContainer.appendChild(gridPanel);

  // Bulk actions panel
  const bulkPanel=document.createElement('div');bulkPanel.className='bg-gray-50 rounded shadow p-4';
  bulkPanel.innerHTML=`
    <h3 class="text-lg font-semibold mb-3">📦 Bulk Actions</h3>
    <div class="space-y-2">
      <button id="fetch-all" class="px-4 py-2 bg-purple-600 hover:bg-purple-700 text-white rounded">Fetch All Finished Jobs</button>
      <p class="text-xs text-gray-600">Downloads all completed job outputs to local workspace</p>
    </div>
  `;
  jobContainer.appendChild(bulkPanel);
  area.appendChild(jobContainer);

  // Build param inputs for both panels
  const sf=document.getElementById('single-fields');
  const gf=document.getElementById('grid-fields');
  keys.forEach(k=>{
    sf.insertAdjacentHTML('beforeend',`
      <div>
        <label class="text-sm font-medium text-gray-700">${k}</label>
        ${createInput(`single-${k}`,exp[k]||'',`Enter ${k} value`)}
      </div>
    `);
    gf.insertAdjacentHTML('beforeend',`
      <div>
        <label class="text-sm font-medium text-gray-700">${k} (comma separated)</label>
        ${createInput(`grid-${k}`,(grid[k]||[]).join(', '),`Enter ${k} values: val1, val2, val3`)}
      </div>
    `);
  });

  // Tutorial toggle
  document.getElementById('toggle-tutorial').onclick=()=>{
    const content=document.getElementById('tutorial-content');
    const btn=document.getElementById('toggle-tutorial');
    if(content.style.display==='none'){
      content.style.display='block';
      btn.textContent='Hide';
    }else{
      content.style.display='none';
      btn.textContent='Show';
    }
  };

  // Add parameter functionality for single jobs
  document.getElementById('single-add-param').onclick=()=>{
    const key=document.getElementById('single-new-param').value.trim();
    if(!key||keys.includes(key))return;keys.push(key);
    sf.insertAdjacentHTML('beforeend',`
      <div>
        <label class="text-sm font-medium text-gray-700">${key}</label>
        ${createInput(`single-${key}`,'',`Enter ${key} value`)}
      </div>
    `);
    gf.insertAdjacentHTML('beforeend',`
      <div>
        <label class="text-sm font-medium text-gray-700">${key} (comma separated)</label>
        ${createInput(`grid-${key}`,'',`Enter ${key} values: val1, val2, val3`)}
      </div>
    `);
    document.getElementById('single-new-param').value='';
    updateHighlighters(keys);
  };

  // Add parameter functionality for grid jobs
  document.getElementById('grid-add-param').onclick=()=>{
    const key=document.getElementById('grid-new-param').value.trim();
    if(!key||keys.includes(key))return;keys.push(key);
    sf.insertAdjacentHTML('beforeend',`
      <div>
        <label class="text-sm font-medium text-gray-700">${key}</label>
        ${createInput(`single-${key}`,'',`Enter ${key} value`)}
      </div>
    `);
    gf.insertAdjacentHTML('beforeend',`
      <div>
        <label class="text-sm font-medium text-gray-700">${key} (comma separated)</label>
        ${createInput(`grid-${key}`,'',`Enter ${key} values: val1, val2, val3`)}
      </div>
    `);
    document.getElementById('grid-new-param').value='';
    updateHighlighters(keys);
  };

  // Event listeners
  document.getElementById('single-submit').onclick=async()=>{
    setButtonLoading('single-submit', true, 'Submitting...');
    try {
      await saveFullConfig(keys);
    const params={};keys.forEach(k=>{const v=document.getElementById(`single-${k}`).value.trim();if(v)params[k]=v;});
    await api('/api/jobs/submit_single',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(params)});
      await refreshJobs(false);
    } finally {
      setButtonLoading('single-submit', false);
    }
  };
  document.getElementById('grid-submit').onclick=async()=>{
    setButtonLoading('grid-submit', true, 'Submitting...');
    try {
      await saveFullConfig(keys);
      await api('/api/jobs/submit',{method:'POST'});
      await refreshJobs(false);
    } finally {
      setButtonLoading('grid-submit', false);
    }
  };
  document.getElementById('fetch-all').onclick=fetchAllFinished;
  updateHighlighters(keys);
}
async function saveFullConfig(keys) {
  const runCmd = document.getElementById('run-command').value;
  const envSetup = document.getElementById('env-setup').value.trim();
  const baseDir = document.getElementById('base-dir').value.trim();
  const filesPush = document.getElementById('files-push').value.split(',').map(s=>s.trim()).filter(Boolean);
  const filesFetch = document.getElementById('files-fetch').value.split(',').map(s=>s.trim()).filter(Boolean);
  const slurmDirectives = document.getElementById('slurm-directives').value;
  
  const grid = {};
  keys.forEach(k=>{
    const v = document.getElementById(`grid-${k}`).value.split(',').map(s=>s.trim()).filter(Boolean);
    if(v.length) grid[k] = v;
  });
  
  const runConfig = { command: runCmd, grid };
  // Always include env_setup field, even if empty
  runConfig.env_setup = envSetup || null;
  
  const fullConfig = {
    run: runConfig,
    remote: { base_dir: baseDir },
    files: { push: filesPush, fetch: filesFetch },
    slurm: { directives: slurmDirectives }
  };
  
  await api('/api/config/full', {
    method: 'PATCH',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(fullConfig)
  });
}

function updateHighlighters(keys) {
  setupHighlighter('base-dir-pre', 'base-dir', keys);
  setupHighlighter('files-push-pre', 'files-push', keys);
  setupHighlighter('files-fetch-pre', 'files-fetch', keys);
  setupHighlighter('slurm-directives-pre', 'slurm-directives', keys);
  setupHighlighter('env-setup-pre', 'env-setup', keys);
  setupHighlighter('run-command-pre', 'run-command', keys);
}

// escape html
function esc(str) {
  return str.replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
}

function highlightCmd(text, validKeys){
  const knownPlaceholders = ['base_dir', 'remote_dir', 'run_dir', ...validKeys];
  return text.replace(/\{([^}]+)\}/g,(m,key)=>{
    if(knownPlaceholders.includes(key))return `<span class="hl-ok">${m}</span>`;
    return `<span class="hl-missing">${m}</span>`;
  });
}

function setupHighlighter(areaId,taId,keys){const ta=document.getElementById(taId);const pre=document.getElementById(areaId);
  const update=()=>{pre.innerHTML=highlightCmd(esc(ta.value),keys);};
  ta.addEventListener('input',update);update();
  ta.addEventListener('scroll',()=>{pre.scrollTop=ta.scrollTop;pre.scrollLeft=ta.scrollLeft;});}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
window.addEventListener('DOMContentLoaded',()=>{
  buildConfigPanels();
  refreshJobs(true); // Show loading on initial load
  setInterval(() => refreshJobs(false), 10000); // Don't show loading on periodic refreshes
}); 