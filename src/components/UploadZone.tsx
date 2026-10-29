import { useId, useRef, useState, type DragEvent, type KeyboardEvent } from 'react';

type UploadZoneProps = {
  disabled?: boolean;
  onFile: (file: File) => void;
};

export function UploadZone({ disabled = false, onFile }: UploadZoneProps) {
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const pick = (fileList: FileList | null) => {
    const file = fileList?.item(0);
    if (file) onFile(file);
  };

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    if (disabled) return;
    pick(event.dataTransfer.files);
  };

  const onDragOver = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    if (!disabled) setDragging(true);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      inputRef.current?.click();
    }
  };

  return (
    <div
      className="upload"
      data-dragging={dragging ? 'true' : 'false'}
      onDragEnter={onDragOver}
      onDragOver={onDragOver}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
    >
      <p className="upload__title">Upuść PDF albo wybierz plik</p>
      <p className="upload__hint">
        Tylko PDF, maksymalnie 10 MB. Walidacja odbywa się w przeglądarce.
      </p>
      <div className="btn-row">
        <button
          type="button"
          className="btn btn--primary"
          disabled={disabled}
          aria-controls={inputId}
          onClick={() => inputRef.current?.click()}
          onKeyDown={onKeyDown}
        >
          Wybierz plik PDF
        </button>
      </div>
      <input
        id={inputId}
        ref={inputRef}
        className="sr-only"
        type="file"
        accept="application/pdf,.pdf"
        disabled={disabled}
        tabIndex={-1}
        onChange={(event) => {
          pick(event.target.files);
          event.target.value = '';
        }}
      />
    </div>
  );
}
