// Keep in sync with ALLOWED_EXTENSIONS in backend/api/routes_ingest.py.
export const DOC_EXTS = ['pdf', 'txt', 'md', 'py', 'js'];
export const AUDIO_EXTS = ['mp3', 'wav', 'm4a', 'ogg', 'oga', 'opus', 'flac', 'webm', 'aac', 'mp4'];
export const IMAGE_EXTS = ['png', 'jpg', 'jpeg', 'webp', 'bmp', 'tif', 'tiff'];

export const UPLOAD_EXTS = [...DOC_EXTS, ...AUDIO_EXTS, ...IMAGE_EXTS];
export const UPLOAD_ACCEPT = UPLOAD_EXTS.map((e) => `.${e}`).join(',');
export const UPLOAD_LABEL = 'PDF, text, code, photos of notes, voice notes';
