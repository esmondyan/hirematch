// File upload handling
const uploadZone = document.getElementById('upload-zone');
const fileInput = document.getElementById('file-input');
const fileList = document.getElementById('file-list');
const uploadBtn = document.getElementById('upload-btn');

if (uploadZone && fileInput) {
    uploadZone.addEventListener('click', () => fileInput.click());

    uploadZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadZone.classList.add('drag-over');
    });
    uploadZone.addEventListener('dragleave', () => {
        uploadZone.classList.remove('drag-over');
    });
    uploadZone.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadZone.classList.remove('drag-over');
        const files = Array.from(e.dataTransfer.files);
        addFiles(files);
    });

    fileInput.addEventListener('change', () => {
        const files = Array.from(fileInput.files);
        addFiles(files);
    });
}

let selectedFiles = [];

function addFiles(files) {
    for (const file of files) {
        const ext = file.name.split('.').pop().toLowerCase();
        if (!['pdf', 'docx', 'txt'].includes(ext)) {
            alert(`不支持的文件格式: ${file.name}，仅支持 PDF/DOCX/TXT`);
            continue;
        }
        if (file.size > 5 * 1024 * 1024) {
            alert(`文件过大: ${file.name}，限制 5MB`);
            continue;
        }
        if (!selectedFiles.find(f => f.name === file.name)) {
            selectedFiles.push(file);
        }
    }
    renderFileList();
}

function removeFile(index) {
    selectedFiles.splice(index, 1);
    renderFileList();
}

function renderFileList() {
    fileList.innerHTML = selectedFiles.map((f, i) => `
        <div class="file-item">
            <span class="file-item-name">${f.name} (${formatSize(f.size)})</span>
            <button class="file-item-remove" onclick="removeFile(${i})">&times;</button>
        </div>
    `).join('');
    uploadBtn.disabled = selectedFiles.length === 0;
    uploadBtn.textContent = selectedFiles.length
        ? `开始匹配分析 (${selectedFiles.length} 份简历)`
        : '开始匹配分析';

    // Update file input to match selected files
    const dt = new DataTransfer();
    selectedFiles.forEach(f => dt.items.add(f));
    fileInput.files = dt.files;
}

function formatSize(bytes) {
    if (bytes < 1024) return bytes + 'B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + 'KB';
    return (bytes / (1024 * 1024)).toFixed(1) + 'MB';
}

// Auto-refresh results page when there are pending candidates
if (document.querySelector('.pending-card')) {
    setTimeout(() => location.reload(), 3000);
}
