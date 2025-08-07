// slurmster dashboard front-end

// Create a persistent HTTP agent for connection pooling and keep-alive
// This solves the issue where each API call was creating a new TCP connection
// with incrementing ephemeral ports (32768-65535 range)
class HTTPClient {
  constructor() {
    // Configure fetch to use keep-alive connections
    // keepalive: true enables connection reuse for multiple requests
    // Connection: keep-alive tells the server to keep the connection open
    // Keep-Alive header sets timeout and max requests per connection
    this.defaultOptions = {
      keepalive: true,
      headers: {
        'Connection': 'keep-alive',
        'Keep-Alive': 'timeout=30, max=100'
      }
    };
  }

  async request(path, opts = {}) {
    // Merge default options with provided options
    const mergedOpts = {
      ...this.defaultOptions,
      ...opts,
      headers: {
        ...this.defaultOptions.headers,
        ...(opts.headers || {})
      }
    };

    const res = await fetch(path, mergedOpts);
    if (!res.ok) throw new Error(await res.text());
    if (res.status === 204) return null;
    return res.json();
  }
}

// Create a singleton HTTP client instance
const httpClient = new HTTPClient();

// Updated api function that uses the HTTP client with connection pooling
async function api(path, opts = {}) {
  return httpClient.request(path, opts);
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
  
  if (jobs.length === 0) {
    // Show helpful message when no jobs are found
    const tr = document.createElement('tr');
    const colCount = 3 + paramKeys.length; // job_id + state + params + actions
    tr.innerHTML = `<td colspan="${colCount}" class="px-6 py-8 text-center text-gray-500">
      <div class="flex flex-col items-center space-y-2">
        <svg class="w-12 h-12 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v10a2 2 0 002 2h8a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012-2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01"></path>
        </svg>
        <p class="text-sm">No jobs found</p>
        <p class="text-xs">Try running "Run Status Check" to discover jobs from the remote system</p>
      </div>
    </td>`;
    tbody.appendChild(tr);
    return;
  }
  
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
  const modal = document.getElementById('browse-modal');
  modal.classList.remove('hidden');
  modal.classList.add('flex');
  
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
        
        // Action buttons for files (not directories)
        const fileExt = file.name.split('.').pop().toLowerCase();
        const canView = isTextFile(fileExt) || isImageFile(fileExt) || isSvgFile(fileExt);
        const viewButton = canView ? `<button onclick="viewFile('${file.name}')" class="px-2 py-1 bg-green-600 hover:bg-green-700 text-white rounded text-xs mr-1">👁️ View</button>` : '';
        
        const actions = file.is_directory ? '' : `
          ${viewButton}
          <button onclick="downloadFile('${file.name}')" class="px-2 py-1 bg-blue-600 hover:bg-blue-700 text-white rounded text-xs">📥 Download</button>
        `;
        
        row.innerHTML = `
          <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900 ${cursor}" ${clickHandler}>
            ${icon} ${file.name}
          </td>
          <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">${file.size}</td>
          <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">${file.date}</td>
          <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">${actions}</td>
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

async function viewFile(fileName) {
  try {
    const filePath = currentBrowsePath ? `${currentBrowsePath}/${fileName}` : fileName;
    const fileExt = fileName.split('.').pop().toLowerCase();
    
    // Show file viewer modal
    const modal = document.getElementById('file-viewer-modal');
    const title = document.getElementById('file-viewer-title');
    const pathDisplay = document.getElementById('file-viewer-path');
    const content = document.getElementById('file-content');
    const downloadBtn = document.getElementById('download-file');
    
    title.textContent = fileName;
    pathDisplay.textContent = filePath;
    
    // Set up download button
    downloadBtn.onclick = () => downloadFile(fileName);
    
    modal.classList.remove('hidden');
    
    // Show loading state
    content.innerHTML = '<div class="flex items-center justify-center h-64"><div class="text-gray-500">Loading...</div></div>';
    
    // Fetch file content
    const params = new URLSearchParams();
    params.append('file_path', filePath);
    
    if (isTextFile(fileExt)) {
      // Load as text
      const response = await fetch(`/api/jobs/${currentBrowseJobId}/download?${params}`);
      const text = await response.text();
      
      content.innerHTML = `<pre class="bg-gray-100 p-4 rounded text-sm overflow-auto whitespace-pre-wrap">${escapeHtml(text)}</pre>`;
    } else if (isImageFile(fileExt)) {
      // Load as raster image
      const imageUrl = `/api/jobs/${currentBrowseJobId}/download?${params}`;
      content.innerHTML = `<div class="flex justify-center"><img src="${imageUrl}" alt="${fileName}" class="max-w-full max-h-full object-contain"/></div>`;
    } else if (isSvgFile(fileExt)) {
      // Load SVG with proper handling
      try {
        const response = await fetch(`/api/jobs/${currentBrowseJobId}/download?${params}`);
        const svgText = await response.text();
        
        // Clean and ensure proper SVG structure
        let cleanSvg = svgText.trim();
        if (!cleanSvg.startsWith('<svg')) {
          throw new Error('Invalid SVG format');
        }
        
        // Wrap in a container with proper sizing
        content.innerHTML = `
          <div class="flex justify-center items-center w-full h-full">
            <div class="max-w-full max-h-full" style="max-width: 90%; max-height: 90%;">
              ${cleanSvg}
            </div>
          </div>
        `;
        
        // Apply some basic styling to the SVG if it doesn't have explicit dimensions
        const svgElement = content.querySelector('svg');
        if (svgElement && !svgElement.style.width && !svgElement.style.height) {
          svgElement.style.maxWidth = '100%';
          svgElement.style.maxHeight = '100%';
          svgElement.style.height = 'auto';
        }
      } catch (error) {
        // Fallback to image approach if SVG parsing fails
        const imageUrl = `/api/jobs/${currentBrowseJobId}/download?${params}`;
        content.innerHTML = `<div class="flex justify-center"><img src="${imageUrl}" alt="${fileName}" class="max-w-full max-h-full object-contain"/></div>`;
      }
    } else {
      // Unsupported file type
      content.innerHTML = `
        <div class="text-center py-8">
          <p class="text-gray-500 mb-4">File type ".${fileExt}" not supported for preview</p>
          <p class="text-sm text-gray-400 mb-2"><strong>Text files:</strong> Programming (py, js, ts, java, c, cpp, etc.), Documentation (md, txt, rst), Config (json, yaml, ini, etc.), Logs, Scripts</p>
          <p class="text-sm text-gray-400"><strong>Images:</strong> png, jpg, jpeg, gif, webp, bmp, ico, svg</p>
          <p class="text-xs text-gray-400 mt-2">Download the file to view it locally</p>
        </div>
      `;
    }
    
  } catch (error) {
    const content = document.getElementById('file-content');
    content.innerHTML = `<div class="text-center py-8 text-red-500">Failed to load file: ${error.message}</div>`;
  }
}

function isTextFile(ext) {
  const textExtensions = [
    // Programming languages
    'py', 'js', 'ts', 'jsx', 'tsx', 'java', 'c', 'cpp', 'cc', 'cxx', 'h', 'hpp', 'cs', 'php', 'rb', 'go', 'rs', 'swift', 'kt', 'scala', 'clj', 'hs', 'ml', 'fs', 'pas', 'pl', 'r', 'jl', 'dart', 'lua', 'nim', 'zig', 'v',
    
    // Web technologies
    'html', 'htm', 'css', 'scss', 'sass', 'less', 'xml', 'vue', 'svelte',
    
    // Data formats
    'json', 'yaml', 'yml', 'toml', 'ini', 'cfg', 'conf', 'properties', 'env', 'csv', 'tsv', 'psv',
    
    // Documentation
    'md', 'markdown', 'txt', 'rst', 'asciidoc', 'adoc', 'tex', 'latex', 'rtf',
    
    // Shell scripts
    'sh', 'bash', 'zsh', 'fish', 'ps1', 'bat', 'cmd',
    
    // Build/config files
    'makefile', 'dockerfile', 'jenkinsfile', 'vagrantfile', 'cmake', 'ninja', 'gradle', 'ant', 'maven', 'sbt', 'bazel',
    
    // Logs and outputs
    'log', 'out', 'err', 'stdout', 'stderr', 'trace', 'debug',
    
    // Database
    'sql', 'sqlite', 'mysql', 'pgsql', 'plsql',
    
    // Scientific/Data
    'ipynb', 'rmd', 'qmd', 'npy', 'npz', 'mat', 'hdf5', 'h5', 'nc', 'cdf',
    
    // License/Readme files
    'license', 'readme', 'changelog', 'authors', 'contributors', 'copying', 'install', 'news', 'todo',
    
    // Misc text formats
    'diff', 'patch', 'gitignore', 'gitattributes', 'editorconfig', 'eslintrc', 'prettierrc', 'babelrc', 'vimrc', 'bashrc', 'zshrc', 'profile',
    
    // Certificate/Key files (text-based)
    'pem', 'crt', 'cert', 'key', 'pub', 'asc', 'sig',
    
    // Other common text files
    'mf', 'manifest', 'spec', 'requirements', 'gemfile', 'podfile', 'brewfile', 'procfile'
  ];
  return textExtensions.includes(ext);
}

function isImageFile(ext) {
  const imageExtensions = [
    // Browser-supported raster formats
    'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'ico'
  ];
  return imageExtensions.includes(ext);
}

function isSvgFile(ext) {
  return ext === 'svg';
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function closeFileViewer() {
  const modal = document.getElementById('file-viewer-modal');
  modal.classList.add('hidden');
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
  const statusIndicator = document.getElementById('status-indicator');
  tbody.innerHTML = '<tr><td colspan="100%" class="px-6 py-8 text-center text-gray-500"><div class="flex items-center justify-center"><svg class="animate-spin -ml-1 mr-3 h-5 w-5 text-gray-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>Running status check...</div></td></tr>';
  if (statusIndicator) {
    statusIndicator.classList.remove('hidden');
    statusIndicator.classList.add('flex');
  }
}

function hideJobsLoading() {
  // This will be handled by renderJobs() which replaces the tbody content
  const statusIndicator = document.getElementById('status-indicator');
  if (statusIndicator) {
    statusIndicator.classList.add('hidden');
    statusIndicator.classList.remove('flex');
  }
}

function showJobsError(message) {
  const tbody = document.getElementById('jobs-tbody');
  const statusIndicator = document.getElementById('status-indicator');
  tbody.innerHTML = `<tr><td colspan="100%" class="px-6 py-8 text-center text-red-500">Error loading jobs: ${message}</td></tr>`;
  if (statusIndicator) {
    statusIndicator.classList.add('hidden');
    statusIndicator.classList.remove('flex');
  }
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

function monitorEnvSetup() {
  const modal = document.getElementById('log-modal');
  const title = document.getElementById('log-title');
  const content = document.getElementById('log-content');
  
  title.textContent = 'Environment Setup';
  content.textContent = '';
  modal.classList.remove('hidden');
  modal.classList.add('flex');
  
  const wsUrl = `${location.origin.replace(/^http/, 'ws')}/ws/env_setup`;
  ws = new WebSocket(wsUrl);
  
  ws.onmessage = (e) => {
    const line = e.data;
    
    // Check for special completion/error markers
    if (line === '__ENV_SETUP_COMPLETE__') {
      content.textContent += '\nEnvironment setup completed! Closing in 3 seconds...\n';
      content.scrollTop = content.scrollHeight;
      setTimeout(() => {
        closeLogModal();
        // Refresh environment status after completion
        checkEnvironmentStatus();
      }, 3000);
      return;
    }
    
    if (line === '__ENV_SETUP_ERROR__') {
      content.textContent += '\nEnvironment setup failed. Please check the output above.\n';
      content.scrollTop = content.scrollHeight;
      return;
    }
    
    content.textContent += line + '\n';
    content.scrollTop = content.scrollHeight;
  };
  
  ws.onclose = () => console.log('env setup ws closed');
  ws.onerror = (error) => {
    console.error('WebSocket error:', error);
    content.textContent += '\nWebSocket connection error. Please try again.\n';
  };
}
document.getElementById('close-modal').addEventListener('click',closeLogModal);

// Browse modal event listeners
document.getElementById('close-browse-modal').addEventListener('click',closeBrowseModal);
document.getElementById('browse-up').addEventListener('click',navigateUp);
document.getElementById('browse-refresh').addEventListener('click',()=>loadDirectory(currentBrowsePath));

// File viewer modal event listener
document.getElementById('close-file-viewer').addEventListener('click',closeFileViewer);

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
  const createTextarea=(id,val='',placeholder='',rows=3)=>`<div class="code-wrapper"><div class="line-numbers" id="${id}-line-numbers"></div><pre id="${id}-pre"></pre><textarea id="${id}" class="input-field code-field" rows="${rows}" placeholder="${placeholder}">${val}</textarea></div>`;
  
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
  const configPanel=document.createElement('div');configPanel.className='bg-white rounded-lg shadow-md border border-gray-200 p-5';
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
  const singlePanel=document.createElement('div');singlePanel.className='bg-white rounded-lg shadow-md border border-gray-200 p-5';
  singlePanel.innerHTML=`
    <h3 class="text-lg font-semibold mb-3">🎯 Single Job Submission</h3>
    <div class="space-y-3">
      <div id="single-fields" class="grid grid-cols-1 md:grid-cols-2 gap-3"></div>
      <div class="flex items-center space-x-2">
        <input id="single-new-param" placeholder="add new parameter" class="input-field flex-1"/>
        <button id="single-add-param" class="px-4 py-2 bg-slate-600 hover:bg-slate-700 text-white rounded text-sm font-medium">Add</button>
      </div>
      <div class="flex space-x-2">
        <button id="single-submit" class="flex-1 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded disabled:bg-gray-400 disabled:cursor-not-allowed font-medium">Submit</button>
        <button id="single-submit-env" class="flex-1 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded font-medium">🔧 Set Up Environment & Submit</button>
      </div>
    </div>
  `;
  jobContainer.appendChild(singlePanel);
  
  // Grid job submission panel  
  const gridPanel=document.createElement('div');gridPanel.className='bg-white rounded-lg shadow-md border border-gray-200 p-5';
  gridPanel.innerHTML=`
    <h3 class="text-lg font-semibold mb-3">🔥 Grid Job Submission</h3>
    <div class="space-y-3">
      <div id="grid-fields" class="grid grid-cols-1 md:grid-cols-2 gap-3"></div>
      <div class="flex items-center space-x-2">
        <input id="grid-new-param" placeholder="add new parameter" class="input-field flex-1"/>
        <button id="grid-add-param" class="px-4 py-2 bg-slate-600 hover:bg-slate-700 text-white rounded text-sm font-medium">Add</button>
      </div>
      <div class="flex space-x-2">
        <button id="grid-submit" class="flex-1 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded disabled:bg-gray-400 disabled:cursor-not-allowed font-medium">Submit</button>
        <button id="grid-submit-env" class="flex-1 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded font-medium">🔧 Set Up Environment & Submit</button>
      </div>
    </div>
  `;
  jobContainer.appendChild(gridPanel);

  // Bulk actions panel
  const bulkPanel=document.createElement('div');bulkPanel.className='bg-slate-50 rounded-lg shadow-md border border-slate-200 p-5';
  bulkPanel.innerHTML=`
    <h3 class="text-lg font-semibold mb-3">📦 Bulk Actions</h3>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
      <div class="space-y-2">
        <button id="status-check" class="w-full px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded font-medium">🔄 Run Status Check</button>
        <p class="text-xs text-gray-600">Refresh job statuses by checking markers and slurm queue</p>
      </div>
      <div class="space-y-2">
        <button id="fetch-all" class="w-full px-4 py-2 bg-amber-600 hover:bg-amber-700 text-white rounded font-medium">📥 Fetch All Finished Jobs</button>
        <p class="text-xs text-gray-600">Downloads all completed job outputs to local workspace</p>
      </div>
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
  document.getElementById('single-submit-env').onclick=async()=>{
    setButtonLoading('single-submit-env', true, 'Setting up environment & submitting...');
    try {
      await saveFullConfig(keys);
      
      // Show environment setup monitor first
      monitorEnvSetup();
      
      // Add delay to let monitor connect
      await new Promise(resolve => setTimeout(resolve, 500));
      
      // Wait for env setup to complete before submitting
      await new Promise((resolve, reject) => {
        const origOnMessage = ws.onmessage;
        ws.onmessage = (e) => {
          origOnMessage(e); // Call original handler
          if (e.data === '__ENV_SETUP_COMPLETE__') {
            resolve();
          } else if (e.data === '__ENV_SETUP_ERROR__') {
            reject(new Error('Environment setup failed'));
          }
        };
      });
      
      // Now submit the job
      const params={};keys.forEach(k=>{const v=document.getElementById(`single-${k}`).value.trim();if(v)params[k]=v;});
      await api('/api/jobs/submit_single',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(params)});
      await refreshJobs(false);
      await checkEnvironmentStatus();
    } catch (error) {
      console.error('Environment setup & submit failed:', error);
    } finally {
      setButtonLoading('single-submit-env', false);
    }
  };
  document.getElementById('grid-submit-env').onclick=async()=>{
    setButtonLoading('grid-submit-env', true, 'Setting up environment & submitting...');
    try {
      await saveFullConfig(keys);
      
      // Show environment setup monitor first
      monitorEnvSetup();
      
      // Add delay to let monitor connect
      await new Promise(resolve => setTimeout(resolve, 500));
      
      // Wait for env setup to complete before submitting
      await new Promise((resolve, reject) => {
        const origOnMessage = ws.onmessage;
        ws.onmessage = (e) => {
          origOnMessage(e); // Call original handler
          if (e.data === '__ENV_SETUP_COMPLETE__') {
            resolve();
          } else if (e.data === '__ENV_SETUP_ERROR__') {
            reject(new Error('Environment setup failed'));
          }
        };
      });
      
      // Now submit the jobs
      await api('/api/jobs/submit',{method:'POST'});
      await refreshJobs(false);
      await checkEnvironmentStatus();
    } catch (error) {
      console.error('Environment setup & submit failed:', error);
    } finally {
      setButtonLoading('grid-submit-env', false);
    }
  };
  document.getElementById('status-check').onclick=async()=>{
    const button = document.getElementById('status-check');
    const originalClass = button.className;
    const originalText = 'Run Status Check';
    
    setButtonLoading('status-check', true, 'Syncing with remote...');
    
    try {
      // Use the comprehensive status sync endpoint
      const response = await api('/api/jobs/status-sync', {method: 'POST'});
      
      // Update the cached jobs with the synced data
      if (response.jobs) {
        cachedJobs = response.jobs;
        paramKeysGlobal = computeParamKeys(response.jobs);
        renderJobs();
      }
      
      // First disable loading state
      setButtonLoading('status-check', false);
      
      // Then show success state with job count
      button.className = button.className.replace('bg-blue-600 hover:bg-blue-700', 'bg-green-600 hover:bg-green-700');
      button.textContent = `✓ Found ${response.jobs_found || 0} jobs`;
      button.disabled = false; // Ensure button is enabled
      
      // Restore original state after delay
      setTimeout(() => {
        button.className = originalClass;
        button.textContent = originalText;
        button.disabled = false;
      }, 3000);
      
    } catch (error) {
      // First disable loading state
      setButtonLoading('status-check', false);
      
      // Then show error state
      button.className = button.className.replace('bg-blue-600 hover:bg-blue-700', 'bg-red-600 hover:bg-red-700');
      button.textContent = '✗ Sync Failed';
      button.disabled = false; // Ensure button is enabled
      
      // Restore original state after delay
      setTimeout(() => {
        button.className = originalClass;
        button.textContent = originalText;
        button.disabled = false;
      }, 3000);
      
      console.error('Status sync failed:', error);
    }
    // No finally block needed since we handle setButtonLoading in try/catch
  };
  document.getElementById('fetch-all').onclick=fetchAllFinished;
  updateHighlighters(keys);
  
  // Check environment status to enable/disable submit buttons
  checkEnvironmentStatus();
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

async function checkEnvironmentStatus() {
  try {
    const envStatus = await api('/api/env/status');
    const singleSubmitBtn = document.getElementById('single-submit');
    const gridSubmitBtn = document.getElementById('grid-submit');
    
    // Disable vanilla submit buttons if remote directory doesn't exist or no env setup marker
    const shouldDisable = !envStatus.remote_dir_exists || !envStatus.env_setup_completed;
    
    if (singleSubmitBtn) {
      singleSubmitBtn.disabled = shouldDisable;
      if (shouldDisable) {
        singleSubmitBtn.title = envStatus.remote_dir_exists 
          ? 'Environment setup required before submitting' 
          : 'Remote directory does not exist';
      } else {
        singleSubmitBtn.title = '';
      }
    }
    
    if (gridSubmitBtn) {
      gridSubmitBtn.disabled = shouldDisable;
      if (shouldDisable) {
        gridSubmitBtn.title = envStatus.remote_dir_exists 
          ? 'Environment setup required before submitting' 
          : 'Remote directory does not exist';
      } else {
        gridSubmitBtn.title = '';
      }
    }
  } catch (error) {
    console.warn('Failed to check environment status:', error);
    // On error, disable the buttons as a safe default
    const singleSubmitBtn = document.getElementById('single-submit');
    const gridSubmitBtn = document.getElementById('grid-submit');
    if (singleSubmitBtn) {
      singleSubmitBtn.disabled = true;
      singleSubmitBtn.title = 'Cannot check environment status';
    }
    if (gridSubmitBtn) {
      gridSubmitBtn.disabled = true;
      gridSubmitBtn.title = 'Cannot check environment status';
    }
  }
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

function setupHighlighter(areaId,taId,keys){
  const ta=document.getElementById(taId);
  const pre=document.getElementById(areaId);
  const lineNumbers=document.getElementById(taId + '-line-numbers');
  
  const updateLineNumbers=()=>{
    // Only count actual newline characters, not wrapped lines
    const textLines = ta.value.split('\n');
    const lineCount = textLines.length;
    
    // Create line numbers with proper spacing for wrapped content
    const taStyle = getComputedStyle(ta);
    const lineHeight = parseFloat(taStyle.lineHeight);
    
    // Clear and rebuild line numbers
    lineNumbers.innerHTML = '';
    
    // For each logical line, calculate if it wraps and position accordingly
    const tempDiv = document.createElement('div');
    tempDiv.style.cssText = `
      position: absolute;
      visibility: hidden;
      white-space: pre-wrap;
      word-wrap: break-word;
      font-family: ${taStyle.fontFamily};
      font-size: ${taStyle.fontSize};
      line-height: ${taStyle.lineHeight};
      width: ${ta.clientWidth - parseInt(taStyle.paddingLeft) - parseInt(taStyle.paddingRight)}px;
      padding: 0;
      border: none;
      margin: 0;
    `;
    document.body.appendChild(tempDiv);
    
    let currentVisualLine = 0;
    
    for (let i = 0; i < lineCount; i++) {
      const lineContent = textLines[i];
      
      // Position the line number at the start of this logical line
      const lineNumber = document.createElement('div');
      lineNumber.textContent = i + 1;
      lineNumber.style.cssText = `
        position: absolute;
        top: ${currentVisualLine * lineHeight + parseInt(taStyle.paddingTop)}px;
        right: 0.5rem;
        line-height: ${lineHeight}px;
        color: #64748b;
      `;
      lineNumbers.appendChild(lineNumber);
      
      // Calculate how many visual lines this logical line takes
      if (lineContent.trim() === '') {
        // Empty line takes exactly 1 visual line
        currentVisualLine += 1;
      } else {
        tempDiv.textContent = lineContent;
        const visualLinesForThisLine = Math.max(1, Math.ceil(tempDiv.scrollHeight / lineHeight));
        currentVisualLine += visualLinesForThisLine;
      }
    }
    
    document.body.removeChild(tempDiv);
    
    // Set the height of line numbers container to match calculated height
    lineNumbers.style.height = `${currentVisualLine * lineHeight + parseInt(taStyle.paddingTop) + parseInt(taStyle.paddingBottom)}px`;
  };
  
  const update=()=>{
    pre.innerHTML=highlightCmd(esc(ta.value),keys);
    updateLineNumbers();
  };
  
  ta.addEventListener('input',update);
  update();
  ta.addEventListener('scroll',()=>{
    pre.scrollTop=ta.scrollTop;
    pre.scrollLeft=ta.scrollLeft;
    lineNumbers.scrollTop=ta.scrollTop;
  });
  
  // Handle resize events to maintain alignment
  const resizeObserver = new ResizeObserver(() => {
    updateLineNumbers();
  });
  resizeObserver.observe(ta);
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
window.addEventListener('DOMContentLoaded',async()=>{
  buildConfigPanels();
  // Perform initial status check with loading indicator
  console.log('🔍 Performing initial status check...');
  await refreshJobs(true); // Show loading on initial load  
  console.log('✅ Initial status check completed');
  setInterval(() => refreshJobs(false), 10000); // Don't show loading on periodic refreshes
}); 