// Plik upuszczony obok strefy wgrywania przeglądarka otworzyłaby zamiast aplikacji.
// Strefa sama wywołuje preventDefault, więc tutaj trafiają tylko upuszczenia poza nią.
function refuseDrop(event: DragEvent): void {
  if (event.defaultPrevented) return;
  event.preventDefault();
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'none';
}

// Zwraca sprzątanie, więc pasuje wprost do useEffect.
export function refuseDropsOutsideZone(): () => void {
  window.addEventListener('dragover', refuseDrop);
  window.addEventListener('drop', refuseDrop);
  return () => {
    window.removeEventListener('dragover', refuseDrop);
    window.removeEventListener('drop', refuseDrop);
  };
}
