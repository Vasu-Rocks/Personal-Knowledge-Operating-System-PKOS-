import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useAuth } from '../context/useAuth';
import { API } from '../api';
import { UploadCloud, FileText, FileAudio, FileImage, CheckCircle2, Loader2, Trash2, Play, Pause, AlertTriangle, Clock, Menu } from 'lucide-react';
import { UPLOAD_EXTS, UPLOAD_ACCEPT, UPLOAD_LABEL, AUDIO_EXTS, IMAGE_EXTS } from '../lib/fileTypes';

function fileIcon(name) {
  const ext = String(name).split('.').pop().toLowerCase();
  if (AUDIO_EXTS.includes(ext)) return FileAudio;
  if (IMAGE_EXTS.includes(ext)) return FileImage;
  return FileText;
}

/** One line of status per document: is it searchable yet, and is its part of the knowledge map built. */
function DocStatus({ doc }) {
  if (doc.index_status === 'INDEXING') return <span className="doc-status"><Loader2 size={11} className="loader" /> Reading the file...</span>;
  if (doc.index_status === 'FAILED') {
    return <span className="doc-status error"><AlertTriangle size={11} /> {doc.index_error || 'Could not read this file'}</span>;
  }
  const { graph_status: status, graph_processed: done, graph_total: total } = doc;
  const map = status === 'COMPLETED' ? 'map ready'
    : status === 'PROCESSING' ? `building map ${done}/${total}`
      : status === 'PENDING' ? 'map queued'
        : status === 'PAUSED' ? `map paused${total ? ` (${done}/${total})` : ''}`
          : status === 'FAILED' ? 'map failed' : null;
  return (
    <span className={`doc-status${status === 'FAILED' ? ' error' : ''}`}>
      {status === 'PROCESSING' ? <Loader2 size={11} className="loader" /> : status === 'PENDING' ? <Clock size={11} /> : <CheckCircle2 size={11} color="#10b981" />}
      Ready to ask{map ? ` · ${map}` : ''}
    </span>
  );
}

/**
 * Documents page: upload, and the list of documents with their status. Opened from the sidebar; the chat stays clear.
 * `shown` refreshes the list each time the page is opened (documents may also be added from another device).
 */
export default function DocumentsView({ shown = true, onMenu }) {
  const { authFetch } = useAuth();
  const [documents, setDocuments] = useState([]);
  const [isHovering, setIsHovering] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState('');
  const [confirmDelete, setConfirmDelete] = useState(null);
  const fileInputRef = useRef(null);

  const fetchDocuments = useCallback(async () => {
    try {
      const res = await authFetch(`${API}/documents`);
      if (res.ok) setDocuments((await res.json()).documents || []);
    } catch (err) {
      console.error('Could not load the documents', err);
    }
  }, [authFetch]);

  useEffect(() => {
    if (shown) fetchDocuments();
  }, [fetchDocuments, shown]);

  // Keep the status live while a file is being read or its map is being built.
  const busy = documents.some((d) => d.graph_status === 'PENDING' || d.graph_status === 'PROCESSING' || d.index_status === 'INDEXING');
  useEffect(() => {
    if (!busy || !shown) return undefined;
    const timer = setInterval(fetchDocuments, 4000);
    return () => clearInterval(timer);
  }, [busy, shown, fetchDocuments]);

  const jobAction = async (docId, action) => {
    try {
      await authFetch(`${API}/graph/jobs/${docId}/${action}`, { method: 'POST' });
    } catch (err) {
      console.error(`Map ${action} failed`, err);
    }
    fetchDocuments();
  };

  const upload = async (file) => {
    if (!file) return;
    const ext = file.name.split('.').pop().toLowerCase();
    if (!UPLOAD_EXTS.includes(ext)) {
      setUploadError(`Unsupported file type ".${ext}". Allowed: ${UPLOAD_LABEL}.`);
      return;
    }
    if (file.size > 50 * 1024 * 1024) {
      setUploadError('File is too large. Maximum size is 50 MB.');
      return;
    }
    setUploadError('');
    setIsUploading(true);
    const formData = new FormData();
    formData.append('file', file);
    try {
      const res = await authFetch(`${API}/upload`, { method: 'POST', body: formData });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setUploadError(typeof data.detail === 'string' ? data.detail : 'Upload failed. Please try again.');
      }
      await fetchDocuments();
    } catch (err) {
      console.error('Upload failed', err);
      setUploadError('Network error. Is PKOS still running?');
    } finally {
      setIsUploading(false);
    }
  };

  const remove = async (docId) => {
    setConfirmDelete(null);
    setDocuments((prev) => prev.filter((d) => d.doc_id !== docId));
    try {
      const res = await authFetch(`${API}/documents/${docId}`, { method: 'DELETE' });
      if (!res.ok) fetchDocuments();
    } catch (err) {
      console.error('Delete failed', err);
      fetchDocuments();
    }
  };

  return (
    <div className="page">
      <div className="page-header">
        {onMenu && <button type="button" className="icon-btn" onClick={onMenu} aria-label="Open menu"><Menu size={20} /></button>}
        <h2>Documents</h2>
      </div>
      <div className="page-body">
        <div
          className={`drop-zone${isHovering ? ' hovering' : ''}`}
          role="button" tabIndex={0} aria-label="Upload a document"
          onDragOver={(e) => { e.preventDefault(); setIsHovering(true); }}
          onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget)) setIsHovering(false); }}
          onDrop={(e) => { e.preventDefault(); setIsHovering(false); if (e.dataTransfer.files.length) upload(e.dataTransfer.files[0]); }}
          onClick={() => fileInputRef.current.click()}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') fileInputRef.current.click(); }}
        >
          <input type="file" ref={fileInputRef} style={{ display: 'none' }} accept={UPLOAD_ACCEPT} data-testid="upload-input"
            onChange={(e) => { upload(e.target.files[0]); e.target.value = null; }} />
          {isUploading ? <Loader2 size={28} className="loader" color="var(--accent-blue)" /> : <UploadCloud size={28} />}
          <span className="drop-title">{isUploading ? 'Uploading...' : 'Drop a file here or click to upload'}</span>
          {!isUploading && <span className="muted-text">{UPLOAD_LABEL}</span>}
        </div>
        {uploadError && <div className="ai-alert ai-alert-error" role="alert"><AlertTriangle size={16} /> {uploadError}</div>}

        <h3 className="list-title">Your documents ({documents.length})</h3>
        {documents.length === 0 && (
          <p className="muted-text">No documents yet. Upload PDFs, notes, code, photos of notes or voice recordings, then ask about them in a chat.</p>
        )}
        <ul className="doc-list">
          {documents.map((doc) => {
            const Icon = fileIcon(doc.filename);
            return (
              <li key={doc.doc_id} className="doc-row" data-testid="doc-row">
                {React.createElement(Icon, { size: 18, className: 'doc-icon' })}
                <div className="doc-main">
                  <span className="doc-name" title={doc.filename}>{doc.filename}</span>
                  <DocStatus doc={doc} />
                </div>
                {confirmDelete === doc.doc_id ? (
                  <span className="doc-confirm">
                    Delete?
                    <button type="button" className="ai-btn ai-btn-danger" onClick={() => remove(doc.doc_id)}>Delete</button>
                    <button type="button" className="ai-btn" onClick={() => setConfirmDelete(null)}>Cancel</button>
                  </span>
                ) : (
                  <span className="doc-actions">
                    {(doc.graph_status === 'PENDING' || doc.graph_status === 'PROCESSING') && (
                      <button type="button" className="icon-btn" title="Pause building the map" aria-label={`Pause map for ${doc.filename}`}
                        onClick={() => jobAction(doc.doc_id, 'pause')}><Pause size={15} /></button>
                    )}
                    {(doc.graph_status === 'PAUSED' || doc.graph_status === 'FAILED') && (
                      <button type="button" className="icon-btn" title="Build the map" aria-label={`Build map for ${doc.filename}`}
                        onClick={() => jobAction(doc.doc_id, 'start')}><Play size={15} /></button>
                    )}
                    <button type="button" className="icon-btn danger" title="Delete" aria-label={`Delete ${doc.filename}`}
                      onClick={() => setConfirmDelete(doc.doc_id)}><Trash2 size={15} /></button>
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
