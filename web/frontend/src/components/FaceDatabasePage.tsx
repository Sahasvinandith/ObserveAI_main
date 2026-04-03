/**
 * FaceDatabasePage.tsx
 * Web equivalent of the PyQt6 DatabaseViewer widget (page 2).
 *
 * Left panel: searchable list of persons in Faces_db/
 * Right panel: main image + scrollable gallery thumbnails
 * Features: rename, delete person, delete individual images, upload new image
 */

import React, { useState, useEffect, useRef } from 'react';

const S: Record<string, React.CSSProperties> = {
  page: {
    height: '100%', display: 'flex', flexDirection: 'column', background: '#0f0a14',
  },
  toolbar: {
    display: 'flex', alignItems: 'center', gap: 10, padding: '10px 16px',
    background: '#130a1a', borderBottom: '1px solid #2e1040', flexShrink: 0,
  },
  toolbarTitle: { fontWeight: 600, fontSize: 14, color: '#ddd', flex: 1 },
  body: { flex: 1, display: 'flex', overflow: 'hidden' },
  leftPanel: {
    width: 220, minWidth: 220, borderRight: '1px solid #2e1040',
    display: 'flex', flexDirection: 'column', background: '#0d0714',
  },
  searchInput: {
    margin: 8, padding: '7px 10px',
    background: '#1a0f1f', border: '1px solid #2e1040',
    borderRadius: 6, color: '#fff', fontSize: 12, outline: 'none',
  },
  personList: { flex: 1, overflowY: 'auto' },
  rightPanel: {
    flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', padding: 16,
  },
  personHeader: {
    display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12,
  },
  personName: { fontSize: 16, fontWeight: 700, color: '#e0c0f0', flex: 1 },
  mainImageWrap: {
    flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
    background: '#000', borderRadius: 6, overflow: 'hidden', marginBottom: 12,
    minHeight: 200, maxHeight: 400, position: 'relative',
  },
  mainImage: { maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' },
  gallery: {
    display: 'flex', gap: 8, overflowX: 'auto', paddingBottom: 4,
  },
  thumbImg: { width: '100%', height: '100%', objectFit: 'cover' },
  emptyState: {
    flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center',
    justifyContent: 'center', color: '#555', gap: 12,
  },
  deleteThumb: {
    position: 'absolute', top: 2, right: 2, background: 'rgba(0,0,0,0.7)',
    border: 'none', color: '#ff8888', cursor: 'pointer', borderRadius: 3,
    fontSize: 10, padding: '1px 4px',
  },
  uploadBtn: {
    padding: '6px 14px', borderRadius: 6, border: '1px dashed #4a1d5e',
    cursor: 'pointer', fontSize: 12, background: 'transparent', color: '#888',
  },
};

const btnStyle = (variant?: 'primary' | 'danger'): React.CSSProperties => ({
  padding: '6px 14px', borderRadius: 6, border: 'none', cursor: 'pointer',
  fontSize: 12, fontWeight: 600,
  background: variant === 'primary' ? '#7a3a8a' : variant === 'danger' ? '#5a1020' : '#2a1535',
  color: variant === 'danger' ? '#ff8888' : '#fff',
});

const personItemStyle = (selected: boolean): React.CSSProperties => ({
  padding: '8px 14px', cursor: 'pointer', fontSize: 13,
  background: selected ? 'rgba(122,58,138,0.3)' : 'transparent',
  color: selected ? '#fff' : '#bbb',
  borderLeft: selected ? '3px solid #7a3a8a' : '3px solid transparent',
  userSelect: 'none',
});

const thumbStyle = (selected: boolean): React.CSSProperties => ({
  width: 90, height: 90, flexShrink: 0, borderRadius: 4, overflow: 'hidden',
  cursor: 'pointer', border: selected ? '2px solid #7a3a8a' : '2px solid transparent',
  background: '#000', position: 'relative',
});

export default function FaceDatabasePage() {
  const [persons, setPersons] = useState<string[]>([]);
  const [filtered, setFiltered] = useState<string[]>([]);
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<string | null>(null);
  const [images, setImages] = useState<string[]>([]);
  const [mainImage, setMainImage] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const fetchPersons = async () => {
    try {
      const res = await fetch('/api/faces');
      const list: string[] = await res.json();
      setPersons(list);
      setFiltered(list);
    } catch {
      setPersons([]);
    }
  };

  useEffect(() => {
    fetchPersons();
  }, []);

  useEffect(() => {
    const q = search.toLowerCase();
    setFiltered(persons.filter((p) => p.toLowerCase().includes(q)));
  }, [search, persons]);

  const loadImages = async (person: string) => {
    setLoading(true);
    try {
      const res = await fetch(`/api/faces/${encodeURIComponent(person)}/images`);
      const imgs: string[] = await res.json();
      setImages(imgs);
      setMainImage(imgs[0] ?? null);
    } catch {
      setImages([]);
    }
    setLoading(false);
  };

  const handleSelectPerson = (name: string) => {
    setSelected(name);
    loadImages(name);
  };

  const handleRename = async () => {
    if (!selected) return;
    const newName = prompt(`Rename "${selected}" to:`, selected);
    if (!newName || newName.trim() === selected) return;
    try {
      const res = await fetch(`/api/faces/${encodeURIComponent(selected)}/rename`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ new_name: newName.trim() }),
      });
      if (!res.ok) {
        const err = await res.json();
        alert(err.detail || 'Rename failed');
        return;
      }
      alert(`Renamed to "${newName.trim()}"`);
      setSelected(newName.trim());
      await fetchPersons();
    } catch {
      alert('Rename failed');
    }
  };

  const handleDeletePerson = async () => {
    if (!selected) return;
    if (!confirm(`Delete person "${selected}" and all their images?`)) return;
    await fetch(`/api/faces/${encodeURIComponent(selected)}`, { method: 'DELETE' });
    setSelected(null);
    setImages([]);
    setMainImage(null);
    await fetchPersons();
  };

  const handleDeleteImage = async (filename: string) => {
    if (!selected) return;
    if (!confirm(`Delete image "${filename}"?`)) return;
    await fetch(`/api/faces/${encodeURIComponent(selected)}/images/${encodeURIComponent(filename)}`, {
      method: 'DELETE',
    });
    await loadImages(selected);
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!selected || !e.target.files?.length) return;
    const file = e.target.files[0];
    const form = new FormData();
    form.append('file', file);
    await fetch(`/api/faces/${encodeURIComponent(selected)}/upload`, { method: 'POST', body: form });
    await loadImages(selected);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const imageUrl = (person: string, filename: string) =>
    `/api/faces/${encodeURIComponent(person)}/images/${encodeURIComponent(filename)}`;

  return (
    <div style={S.page}>
      <div style={S.toolbar}>
        <span style={S.toolbarTitle}>Face Database</span>
        <button style={btnStyle()} onClick={fetchPersons}>Refresh</button>
      </div>

      <div style={S.body}>
        {/* Left Panel */}
        <div style={S.leftPanel}>
          <input
            style={S.searchInput}
            placeholder="Search persons..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <div style={S.personList}>
            {filtered.map((p) => (
              <div
                key={p}
                style={personItemStyle(selected === p)}
                onClick={() => handleSelectPerson(p)}
              >
                {p}
              </div>
            ))}
            {filtered.length === 0 && (
              <div style={{ padding: 12, color: '#555', fontSize: 12 }}>
                {persons.length === 0 ? 'No persons in database.' : 'No matches.'}
              </div>
            )}
          </div>
        </div>

        {/* Right Panel */}
        <div style={S.rightPanel}>
          {!selected ? (
            <div style={S.emptyState}>
              <span style={{ fontSize: 48 }}>👤</span>
              <div style={{ fontSize: 15, fontWeight: 600 }}>Select a person</div>
              <div style={{ fontSize: 12 }}>Choose from the list to view their face images.</div>
            </div>
          ) : (
            <>
              <div style={S.personHeader}>
                <div style={S.personName}>{selected}</div>
                <button style={btnStyle('primary')} onClick={handleRename}>Rename</button>
                <button style={btnStyle('danger')} onClick={handleDeletePerson}>Delete</button>
              </div>

              {loading ? (
                <div style={{ color: '#666', textAlign: 'center', paddingTop: 40 }}>Loading...</div>
              ) : images.length === 0 ? (
                <div style={{ color: '#555', textAlign: 'center', paddingTop: 40 }}>
                  No images found for this person.
                </div>
              ) : (
                <>
                  {/* Main Image */}
                  <div style={S.mainImageWrap}>
                    {mainImage && (
                      <img
                        style={S.mainImage}
                        src={imageUrl(selected, mainImage)}
                        alt={mainImage}
                      />
                    )}
                  </div>

                  {/* Gallery */}
                  <div style={S.gallery}>
                    {images.map((img) => (
                      <div
                        key={img}
                        style={thumbStyle(mainImage === img)}
                        onClick={() => setMainImage(img)}
                      >
                        <img
                          style={S.thumbImg}
                          src={imageUrl(selected, img)}
                          alt={img}
                          loading="lazy"
                        />
                        <button
                          style={S.deleteThumb}
                          onClick={(e) => { e.stopPropagation(); handleDeleteImage(img); }}
                          title="Delete this image"
                        >
                          ×
                        </button>
                      </div>
                    ))}

                    {/* Upload button */}
                    <div
                      style={{ ...thumbStyle(false), display: 'flex', alignItems: 'center', justifyContent: 'center' }}
                      onClick={() => fileInputRef.current?.click()}
                      title="Upload new face image"
                    >
                      <span style={{ fontSize: 24, color: '#555' }}>+</span>
                      <input
                        ref={fileInputRef}
                        type="file"
                        accept="image/*"
                        style={{ display: 'none' }}
                        onChange={handleUpload}
                      />
                    </div>
                  </div>
                </>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
