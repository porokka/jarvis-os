import React, { useState, useEffect } from 'react';

interface FileNode {
  name: string;
  type: 'file' | 'directory';
  content?: string;
  children?: FileNode[];
}

const CodeEditor = () => {
  const [files, setFiles] = useState<FileNode[]>([]);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState<string>('');
  const [isExplorerOpen, setIsExplorerOpen] = useState(true);

  // Mock file structure
  useEffect(() => {
    const mockFiles: FileNode[] = [
      {
        name: 'src',
        type: 'directory',
        children: [
          {
            name: 'components',
            type: 'directory',
            children: [
              { name: 'App.tsx', type: 'file', content: '/* App component */' },
              { name: 'Header.tsx', type: 'file', content: '/* Header component */' }
            ]
          },
          { name: 'index.tsx', type: 'file', content: '/* Main entry */' },
          { name: 'utils', type: 'directory', children: [{ name: 'helpers.ts', type: 'file', content: '/* Helper functions */' }] }
        ]
      },
      {
        name: 'public',
        type: 'directory',
        children: [
          { name: 'index.html', type: 'file', content: '<html>...</html>' }
        ]
      },
      { name: 'package.json', type: 'file', content: '{/* package info */}' },
      { name: 'README.md', type: 'file', content: '# Jarvis OS' }
    ];
    setFiles(mockFiles);
  }, []);

  const handleFileSelect = (fileName: string, content?: string) => {
    setSelectedFile(fileName);
    setFileContent(content || '');
  };

  const handleContentChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setFileContent(e.target.value);
  };

  const renderFileTree = (nodes: FileNode[], depth = 0) => {
    return (
      <ul className="file-tree">
        {nodes.map((node, index) => (
          <li key={index} className="file-item">
            <div
              className={`file-node ${node.type} ${selectedFile === node.name ? 'selected' : ''}`}
              onClick={() => {
                if (node.type === 'file' && node.content) {
                  handleFileSelect(node.name, node.content);
                }
              }}
            >
              {node.name}
            </div>
            {node.type === 'directory' && node.children && (
              <div className="children">
                {renderFileTree(node.children, depth + 1)}
              </div>
            )}
          </li>
        ))}
      </ul>
    );
  };

  return (
    <div className="code-editor">
      <div className="editor-header">
        <h3>Code Editor</h3>
        <button
          className="toggle-explorer"
          onClick={() => setIsExplorerOpen(!isExplorerOpen)}
        >
          {isExplorerOpen ? 'Hide Explorer' : 'Show Explorer'}
        </button>
      </div>

      <div className="editor-container">
        {isExplorerOpen && (
          <div className="file-explorer">
            <h4>File Explorer</h4>
            {renderFileTree(files)}
          </div>
        )}

        <div className="editor-area">
          <div className="editor-toolbar">
            <span className="file-name">{selectedFile || 'Select a file'}</span>
          </div>
          <textarea
            className="code-textarea"
            value={fileContent}
            onChange={handleContentChange}
            placeholder="Edit code here..."
          />
        </div>
      </div>
    </div>
  );
};

export { CodeEditor };