import { useRef, useState, type DragEvent } from 'react';
import { MAX_FILE_MB } from '../../lib/config';
import { Button } from '../atoms/Button';

type UploadZoneProps = {
  onFile: (file: File) => void;
};

export function UploadZone({ onFile }: UploadZoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const pick = (files: FileList | null) => {
    const file = files?.[0];
    if (file) onFile(file);
  };

  const onDragOver = (event: DragEvent) => {
    event.preventDefault();
    setDragging(true);
  };

  // dragleave przychodzi też przy wejściu kursora na element wewnątrz strefy.
  const onDragLeave = (event: DragEvent<HTMLDivElement>) => {
    const { relatedTarget, currentTarget } = event;
    if (!(relatedTarget instanceof Node && currentTarget.contains(relatedTarget))) {
      setDragging(false);
    }
  };

  const onDrop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    pick(event.dataTransfer.files);
  };

  return (
    <div
      className="upload"
      data-dragging={dragging}
      onDragEnter={onDragOver}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
    >
      <p className="muted">PDF, maks. {MAX_FILE_MB} MB</p>
      <Button variant="primary" onClick={() => inputRef.current?.click()}>
        Wybierz plik
      </Button>
      <input
        ref={inputRef}
        type="file"
        accept="application/pdf,.pdf"
        hidden
        onChange={(event) => {
          pick(event.target.files);
          event.target.value = '';
        }}
      />
    </div>
  );
}
