import React, { useState } from 'react'
import { useStudioStore } from '../../store/studioStore'
import { ContentViewer } from './ContentViewer'
import { NoteEditor } from './NoteEditor'
import type { GeneratedContent, Note, LibraryTab } from '../../types'

const TYPE_ICONS: Record<string, string> = {
  'learning-plan': '\u{1F4C5}', 'study-guide': '\u{1F4D6}', 'flashcards': '\u{1F0CF}',
  'quiz': '\u{1F9EA}', 'progress-report': '\u{1F4CA}',
}

interface ContentLibraryProps {
  planId: string
  activeTab: LibraryTab
  onTabChange: (tab: LibraryTab) => void
}

export const ContentLibrary: React.FC<ContentLibraryProps> = ({
  planId, activeTab: initialTab, onTabChange,
}) => {
  const [activeTab, setActiveTab] = useState<LibraryTab>(initialTab)
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const [viewingContent, setViewingContent] = useState<GeneratedContent | null>(null)
  const [editingNote, setEditingNote] = useState<Note | null>(null)
  const [showNewNote, setShowNewNote] = useState(false)
  const { generatedContents, notes, addNote, updateNote, deleteNote } = useStudioStore()

  const handleTabChange = (tab: LibraryTab) => { setActiveTab(tab); onTabChange(tab) }
  const fmt = (iso: string) => new Date(iso).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })

  const handleExport = (c: GeneratedContent) => {
    const b = new Blob([c.content], { type: 'text/markdown;charset=utf-8' })
    const u = URL.createObjectURL(b)
    Object.assign(document.createElement('a'), { href: u, download: c.title + '.md' }).click()
    URL.revokeObjectURL(u)
  }

  const handleSaveNote = (d: { id?: string; title: string; content: string }) => {
    if (d.id) updateNote(d.id, { title: d.title, content: d.content, updatedAt: new Date().toISOString() })
    else addNote({ id: 'note-' + Date.now(), title: d.title, content: d.content, updatedAt: new Date().toISOString() })
    setEditingNote(null); setShowNewNote(false)
  }

  const handleDeleteNote = (id: string) => { if (confirm('\u786E\u5B9A\u5220\u9664\uFF1F')) deleteNote(id) }

  return (
    <div className="flex flex-col h-full">
      <div className="flex border-b border-border dark:border-dark-border mx-3">
        {(['ai-generated', 'my-notes'] as LibraryTab[]).map(tab => (
          <button key={tab} onClick={() => handleTabChange(tab)}
            className={`flex-1 py-2 text-sm transition-all duration-50 ${activeTab === tab ? 'border-b-2 border-primary text-primary font-medium' : 'text-text-secondary hover:text-text-primary'}`}>
            {tab === 'ai-generated' ? 'AI \u751F\u6210' : '\u6211\u7684\u7B14\u8BB0'}
          </button>
        ))}
      </div>
      <div className="flex-1 overflow-y-auto scrollbar-thin px-3 py-2">
        {activeTab === 'ai-generated' ? (
          generatedContents.length === 0 ? (
            <p className="text-sm text-text-secondary text-center py-6">{'\u70B9\u51FB\u4E0A\u65B9\u5DE5\u5177\u5361\u7247\u751F\u6210\u5185\u5BB9'}</p>
          ) : (
            <ul className="flex flex-col gap-0.5">
              {[...generatedContents].reverse().map(c => (
                <li key={c.id} onClick={() => setViewingContent(c)}
                  onMouseEnter={() => setHoveredId(c.id)} onMouseLeave={() => setHoveredId(null)}
                  className="flex items-center justify-between h-9 px-2 rounded-lg hover:bg-surface-tertiary dark:hover:bg-dark-surface transition-colors duration-50 cursor-pointer">
                  <span className="flex items-center gap-1.5 text-sm text-text-primary dark:text-dark-text truncate">
                    <span aria-hidden="true">{TYPE_ICONS[c.type] || '\u{1F4C4}'}</span>{c.title}
                  </span>
                  <span className="flex items-center gap-2 flex-shrink-0">
                    <span className="text-xs text-text-secondary">{fmt(c.createdAt)}</span>
                    {hoveredId === c.id && (
                      <button aria-label="Export" onClick={(e) => { e.stopPropagation(); handleExport(c) }}
                        className="text-xs text-text-secondary hover:text-primary transition-colors duration-50">{'\u2193'}</button>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          )
        ) : (
          <div className="flex flex-col h-full">
            {notes.length === 0 ? (
              <p className="text-sm text-text-secondary text-center py-6">{'\u8FD8\u6CA1\u6709\u7B14\u8BB0'}</p>
            ) : (
              <ul className="flex flex-col gap-0.5 flex-1">
                {[...notes].reverse().map(n => (
                  <li key={n.id} onClick={() => setEditingNote(n)}
                    onMouseEnter={() => setHoveredId(n.id)} onMouseLeave={() => setHoveredId(null)}
                    className="flex items-center justify-between h-9 px-2 rounded-lg hover:bg-surface-tertiary dark:hover:bg-dark-surface transition-colors duration-50 cursor-pointer">
                    <span className="text-sm text-text-primary dark:text-dark-text truncate">{'\u{1F4DD}'} {n.title}</span>
                    <span className="flex items-center gap-2 flex-shrink-0">
                      <span className="text-xs text-text-secondary">{fmt(n.updatedAt)}</span>
                      {hoveredId === n.id && (
                        <button aria-label="Delete" onClick={(e) => { e.stopPropagation(); handleDeleteNote(n.id) }}
                          className="text-xs text-red-400 hover:text-red-600 transition-colors duration-50">{'\u2715'}</button>
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            <button onClick={() => setShowNewNote(true)} aria-label="New note"
              className="mt-2 w-full h-9 rounded-lg border border-dashed border-border text-sm text-text-secondary hover:border-primary hover:text-primary transition-all duration-50">
              + {'\u65B0\u5EFA\u7B14\u8BB0'}
            </button>
          </div>
        )}
      </div>
      {viewingContent && <ContentViewer content={viewingContent} onClose={() => setViewingContent(null)} />}
      {(editingNote || showNewNote) && (
        <NoteEditor note={editingNote || undefined} onSave={handleSaveNote}
          onClose={() => { setEditingNote(null); setShowNewNote(false) }} planId={planId} />
      )}
    </div>
  )
}
