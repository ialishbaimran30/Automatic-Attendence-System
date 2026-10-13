import React, { useEffect, useRef, useState } from 'react';

export default function EnrollmentPhotos({ photos, onPhotos, disabled }) {
  const [camera, setCamera] = useState(false), [error, setError] = useState('');
  const video = useRef(null), stream = useRef(null);
  useEffect(() => () => stream.current?.getTracks().forEach(t => t.stop()), []);
  useEffect(() => { if (camera && video.current) { video.current.srcObject = stream.current; video.current.play().catch(() => {}); } }, [camera]);
  async function toggle() {
    setError('');
    if (camera) { stream.current?.getTracks().forEach(t => t.stop()); setCamera(false); return; }
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error('Webcam capture needs HTTPS or localhost. You can also select a photo file.');
      stream.current = await navigator.mediaDevices.getUserMedia({ video: { width:640, height:480 }, audio:false }); setCamera(true);
    } catch (err) { setError(`Cannot open webcam: ${err.message}. Allow camera access or choose a photo file.`); }
  }
  async function capture() {
    if (!video.current?.videoWidth) { setError('Wait for the webcam preview before capturing.'); return; }
    const canvas = document.createElement('canvas'); canvas.width = video.current.videoWidth; canvas.height = video.current.videoHeight;
    canvas.getContext('2d').drawImage(video.current,0,0);
    const blob = await new Promise(resolve => canvas.toBlob(resolve,'image/jpeg',.92));
    if (!blob) { setError('Could not capture the frame. Retake the selfie.'); return; }
    onPhotos([new File([blob], 'live-selfie.jpg', { type:'image/jpeg' })]); setError('');
  }
  return <><label>Photos<input type="file" accept="image/jpeg,image/png" capture="user" multiple disabled={disabled}
    onChange={e => onPhotos(Array.from(e.target.files || []))} /></label>
    <button type="button" disabled={disabled} onClick={toggle}>{camera ? 'Stop enrollment camera' : 'Use enrollment webcam'}</button>
    {camera && <><div className="camera"><video ref={video} autoPlay playsInline muted /></div><button type="button" disabled={disabled} onClick={capture}>Use this selfie</button></>}
    {photos.length > 0 && <p role="status">{photos.length} photo(s) selected. Submit below to validate liveness and enroll.</p>}
    {error && <p role="alert" className="error">{error}</p>}</>;
}
