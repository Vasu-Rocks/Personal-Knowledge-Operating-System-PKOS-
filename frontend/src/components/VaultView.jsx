import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useAuth } from '../context/useAuth';
import { API } from '../api';
import { UploadCloud, FileText, Database, LogOut, CheckCircle2, Loader2, Trash2, Settings, Play, Pause, AlertTriangle, Clock, Network, Map as MapIcon } from 'lucide-react';
import SettingsView from './SettingsView';
import ConnectionsView from './ConnectionsView';
import KnowledgeMapView from './KnowledgeMapView';
import { UPLOAD_EXTS, UPLOAD_ACCEPT, UPLOAD_LABEL } from '../lib/fileTypes';

export default function VaultView({ width = 250, onOpenSetup, onAiChanged }) {
  const { authFetch, logout, user } = useAuth();
  const [documents, setDocuments] = useState([]);
  const [isHovering, setIsHovering] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [hoveredIndex, setHoveredIndex] = useState(null);
  const [showSettings, setShowSettings] = useState(false);
  const [showConnections, setShowConnections] = useState(false);
  const [showMap, setShowMap] = useState(false);
  const [uploadError, setUploadError] = useState('');
  const fileInputRef = useRef(null);

  const fetchDocuments = useCallback(async () => {
    try {
      const res = await authFetch(`${API}/documents`);
      if (res.ok) {
        const data = await res.json();
        setDocuments(data.documents || []);
      }
    } catch (err) {
      console.error("Failed to sync vault state:", err);
    }
  }, [authFetch]);

  useEffect(() => {
    fetchDocuments();
  }, [fetchDocuments]);

  // Poll while any graph job is queued or running so progress stays live.
  const hasActiveJob = documents.some(d =>
    d.graph_status === 'PENDING' || d.graph_status === 'PROCESSING' || d.index_status === 'INDEXING'
  );
  useEffect(() => {
    if (!hasActiveJob) return;
    const timer = setInterval(fetchDocuments, 4000);
    return () => clearInterval(timer);
  }, [hasActiveJob, fetchDocuments]);

  const handleJobAction = async (docId, action, e) => {
    e.stopPropagation();
    try {
      await authFetch(`${API}/graph/jobs/${docId}/${action}`, { method: 'POST' });
    } catch (err) {
      console.error(`Graph job ${action} failed`, err);
    }
    fetchDocuments();
  };

  const renderGraphStatus = (doc) => {
    const { graph_status: status, graph_processed: done, graph_total: total, graph_error: error } = doc;
    const small = { fontSize: '11px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '4px' };
    if (status === 'COMPLETED') {
      return <span style={small}><CheckCircle2 size={10} color="#10b981" /> Graph ready</span>;
    }
    if (status === 'PROCESSING' || status === 'PENDING') {
      const pct = total ? Math.round((done / total) * 100) : 0;
      return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
          <span style={small}>
            {status === 'PENDING' ? <Clock size={10} /> : <Loader2 size={10} className="loader" color="var(--accent-blue)" />}
            {status === 'PENDING' ? 'Graph queued' : `Building graph ${done}/${total}`}
          </span>
          <div style={{ height: '3px', borderRadius: '2px', background: 'rgba(255,255,255,0.08)' }}>
            <div style={{ height: '100%', width: `${pct}%`, borderRadius: '2px', background: 'var(--accent-blue)', transition: 'width 0.4s' }} />
          </div>
        </div>
      );
    }
    if (status === 'PAUSED') {
      return <span style={small}><Pause size={10} /> Graph paused{total ? ` (${done}/${total})` : ''}</span>;
    }
    if (status === 'FAILED') {
      return <span style={{ ...small, color: '#ef4444' }} title={error || ''}><AlertTriangle size={10} /> Graph failed{total ? ` at ${done}/${total}` : ''}</span>;
    }
    return null;
  };

  const iconButton = {
    background: 'transparent', border: 'none', cursor: 'pointer', padding: '4px',
    display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: '4px'
  };

  const handleFileUpload = async (file) => {
    if (!file) return;
    // Client-side pre-validation
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
    formData.append("file", file);
    try {
      const res = await authFetch(`${API}/upload`, { method: 'POST', body: formData });
      if (res.ok) {
        setUploadError('');
        await fetchDocuments();
      } else {
        const data = await res.json().catch(() => ({}));
        setUploadError(data.detail || 'Upload failed. Please try again.');
      }
    } catch (err) {
      console.error("Upload failed", err);
      setUploadError('Network error. Is the server running?');
    } finally {
      setIsUploading(false);
    }
  };

  const handleDelete = async (docId, e) => {
    e.stopPropagation(); // Prevent row click events
    
    // 1. Optimistic UI update (instantly remove from screen)
    setDocuments(prev => prev.filter(doc => doc.doc_id !== docId));
    
    try {
      // 2. Cascade delete on the backend
      const res = await authFetch(`${API}/documents/${docId}`, {
        method: 'DELETE'
      });
      if (!res.ok) {
        console.error("Failed to delete document from server.");
        // If it fails, we should really sync back with the server state
        fetchDocuments(); 
      }
    } catch (err) {
      console.error("Delete request failed:", err);
      fetchDocuments();
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setIsHovering(false);
    const files = e.dataTransfer.files;
    if (files.length > 0) handleFileUpload(files[0]);
  };

  return (
    <div className="pane-left" style={{ width: `${width}px` }}>
      {/* Header */}
      <div style={{ padding: '20px', borderBottom: 'var(--pane-border)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '8px' }}>
          <div style={{ background: 'var(--accent-glow)', padding: '8px', borderRadius: 'var(--radius-sm)' }}>
            <Database size={20} color="var(--accent-blue)" />
          </div>
          <h1 style={{ fontSize: '16px', fontWeight: '600' }}>Knowledge Vault</h1>
        </div>
        <p style={{ fontSize: '12px', color: 'var(--text-secondary)', lineHeight: 1.4 }}>
          Cryptographically isolated document vectors bound exclusively to your key.
        </p>
      </div>

      {/* Upload Zone */}
      <div style={{ padding: '20px', borderBottom: 'var(--pane-border)' }}>
        <div
          onDragOver={(e) => { e.preventDefault(); setIsHovering(true); }}
          onDragLeave={(e) => {
            if (!e.currentTarget.contains(e.relatedTarget)) {
              setIsHovering(false);
            }
          }}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current.click()}
          style={{
            border: `1px dashed ${isHovering ? 'var(--accent-blue)' : 'rgba(255,255,255,0.1)'}`,
            background: isHovering ? 'var(--accent-glow)' : 'rgba(0,0,0,0.2)',
            borderRadius: 'var(--radius-md)', padding: '24px 16px',
            display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px',
            cursor: 'pointer', transition: 'all var(--transition-fast)'
          }}
        >
          <input 
            type="file" ref={fileInputRef} style={{ display: 'none' }}
            onChange={(e) => {
              handleFileUpload(e.target.files[0]);
              e.target.value = null; // Fix Issue 6: Allow re-uploading same file instantly
            }}
            accept={UPLOAD_ACCEPT}
          />
          {isUploading ? (
             <Loader2 size={28} color="var(--accent-blue)" className="loader" />
          ) : (
             <UploadCloud size={28} color={isHovering ? 'var(--accent-blue)' : 'var(--text-muted)'} />
          )}
          <span style={{ fontSize: '13px', color: isHovering ? 'var(--text-primary)' : 'var(--text-secondary)', textAlign: 'center' }}>
            {isUploading ? 'Hashing Vectors...' : 'Drop a file here or click to browse'}
            {!isUploading && <><br /><span style={{ fontSize: '11px', opacity: 0.7 }}>{UPLOAD_LABEL}</span></>}
          </span>
        </div>
        {uploadError && (
          <div style={{ color: '#ef4444', fontSize: '12px', marginTop: '8px', display: 'flex', alignItems: 'center', gap: '4px' }}>
            <span>⚠</span> {uploadError}
          </div>
        )}
      </div>

      {/* Roster */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '20px 12px' }}>
        <h3 style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '1px', color: 'var(--text-muted)', marginBottom: '16px', paddingLeft: '8px' }}>
          Indexed Matrices ({documents.length})
        </h3>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          {documents.map((doc, idx) => (
            <div 
              key={doc.doc_id}
              onMouseEnter={() => setHoveredIndex(idx)}
              onMouseLeave={() => setHoveredIndex(null)}
              style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 12px',
                borderRadius: 'var(--radius-sm)', cursor: 'default',
                transition: 'background var(--transition-fast)',
                background: hoveredIndex === idx ? 'var(--bg-surface)' : 'transparent'
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px', overflow: 'hidden' }}>
                <FileText size={16} color="var(--text-secondary)" flexShrink={0} />
                <div style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
                  <span style={{ fontSize: '13px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {doc.filename}
                  </span>
                  <span style={{ fontSize: '11px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '4px' }}>
                    {doc.index_status === 'INDEXING' ? (
                      <><Loader2 size={10} className="loader" color="var(--accent-blue)" /> Indexing vectors...</>
                    ) : doc.index_status === 'FAILED' ? (
                      <><AlertTriangle size={10} color="#ef4444" /> <span style={{color:'#ef4444'}}>{doc.index_error || 'Index failed'}</span></>
                    ) : (
                      <><CheckCircle2 size={10} color="#10b981" /> Indexed</>
                    )}
                  </span>
                  {renderGraphStatus(doc)}
                </div>
              </div>

              {/* Graph job controls (visible on hover) */}
              {hoveredIndex === idx && (doc.graph_status === 'PENDING' || doc.graph_status === 'PROCESSING') && (
                <button onClick={(e) => handleJobAction(doc.doc_id, 'pause', e)} style={iconButton} title="Pause graph building">
                  <Pause size={14} color="var(--text-secondary)" />
                </button>
              )}
              {hoveredIndex === idx && (doc.graph_status === 'PAUSED' || doc.graph_status === 'FAILED') && (
                <button onClick={(e) => handleJobAction(doc.doc_id, 'start', e)} style={iconButton}
                  title={doc.graph_status === 'FAILED' ? 'Retry graph building' : 'Build graph'}>
                  <Play size={14} color="var(--accent-blue)" />
                </button>
              )}
              
              {/* Delete Button (Visible on Hover) */}
              {hoveredIndex === idx && (
                <button 
                  onClick={(e) => handleDelete(doc.doc_id, e)}
                  style={{
                    background: 'transparent',
                    border: 'none',
                    cursor: 'pointer',
                    padding: '4px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    borderRadius: '4px',
                    transition: 'background var(--transition-fast)'
                  }}
                  onMouseEnter={(e) => e.currentTarget.style.background = 'rgba(239, 68, 68, 0.1)'}
                  onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}
                >
                  <Trash2 size={14} color="#ef4444" />
                </button>
              )}
            </div>
          ))}
        </div>
        {uploadError && (
          <div style={{ color: '#ef4444', fontSize: '12px', marginTop: '8px', display: 'flex', alignItems: 'center', gap: '4px' }}>
            <span>⚠</span> {uploadError}
          </div>
        )}
      </div>

      {/* System Footer */}
      <div style={{ padding: '16px', borderTop: 'var(--pane-border)', display: 'flex', flexDirection: 'column', gap: '12px' }}>
        {user && (
          <div style={{ 
            padding: '12px', 
            background: 'rgba(255, 255, 255, 0.02)', border: 'var(--pane-border)', 
            borderRadius: 'var(--radius-md)', display: 'flex', flexDirection: 'column', gap: '4px', position: 'relative'
          }}>
            <span style={{ fontSize: '13px', fontWeight: '600', color: 'var(--text-primary)' }}>
              {user.name}
            </span>
            <span style={{ fontSize: '11px', color: 'var(--accent-blue)', fontFamily: 'monospace' }}>
              @{user.username}
            </span>
            <button 
              onClick={() => setShowSettings(true)}
              style={{
                position: 'absolute', right: '12px', top: '50%', transform: 'translateY(-50%)',
                background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', padding: '4px'
              }}
            >
              <Settings size={16} />
            </button>
          </div>
        )}
        <button 
          onClick={() => setShowMap(true)}
          style={{
            display: 'flex', alignItems: 'center', gap: '8px', 
            fontSize: '13px', color: 'var(--text-secondary)', width: '100%',
            padding: '8px', borderRadius: 'var(--radius-sm)', border: '1px solid transparent'
          }}
        >
          <MapIcon size={16} /> Knowledge map
        </button>
        <button 
          onClick={() => setShowConnections(true)}
          style={{
            display: 'flex', alignItems: 'center', gap: '8px', 
            fontSize: '13px', color: 'var(--text-secondary)', width: '100%',
            padding: '8px', borderRadius: 'var(--radius-sm)', border: '1px solid transparent'
          }}
        >
          <Network size={16} /> Connections
        </button>
        <button 
          onClick={logout}
          style={{
            display: 'flex', alignItems: 'center', gap: '8px', 
            fontSize: '13px', color: 'var(--text-muted)', width: '100%',
            padding: '8px', borderRadius: 'var(--radius-sm)', border: '1px solid transparent'
          }}
        >
          <LogOut size={16} /> Secure Disconnect
        </button>
      </div>
      
      {showSettings && (
        <SettingsView
          onClose={() => setShowSettings(false)}
          onSaved={onAiChanged}
          onOpenSetup={onOpenSetup && (() => { setShowSettings(false); onOpenSetup(); })}
        />
      )}
      {showConnections && <ConnectionsView onClose={() => setShowConnections(false)} />}
      {showMap && <KnowledgeMapView onClose={() => setShowMap(false)} />}
    </div>
  );
}
