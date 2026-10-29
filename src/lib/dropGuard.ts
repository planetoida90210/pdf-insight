// A file dropped next to the upload zone would make the browser open it in place of the app.
// The zone calls preventDefault itself, so only drops outside it get here.
function refuseDrop(event: DragEvent): void {
  if (event.defaultPrevented) return;
  event.preventDefault();
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'none';
}

// Returns the cleanup, so it fits useEffect directly.
export function refuseDropsOutsideZone(): () => void {
  window.addEventListener('dragover', refuseDrop);
  window.addEventListener('drop', refuseDrop);
  return () => {
    window.removeEventListener('dragover', refuseDrop);
    window.removeEventListener('drop', refuseDrop);
  };
}
