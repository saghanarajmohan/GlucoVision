import { useEffect, useRef, useState } from "react";

export default function AuthenticatedImage({ src, token, alt, className }) {
  const [objectUrl, setObjectUrl] = useState("");
  const [failedSrc, setFailedSrc] = useState("");
  const host = useRef(null);
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    if (!host.current || typeof IntersectionObserver === "undefined") { setVisible(true); return undefined; }
    const observer = new IntersectionObserver(([entry]) => { if (entry.isIntersecting) { setVisible(true); observer.disconnect(); } }, { rootMargin: "240px" });
    observer.observe(host.current);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (!visible || !src || !token) return undefined;
    let active = true;
    let created = "";
    fetch(src.startsWith("/api/") ? src : `/api${src}`, { headers: { Authorization: `Bearer ${token}` } })
      .then((response) => { if (!response.ok) throw new Error("Image unavailable"); return response.blob(); })
      .then((blob) => { if (active) { created = URL.createObjectURL(blob); setObjectUrl(created); } })
      .catch(() => { if (active) setFailedSrc(src); });
    return () => { active = false; if (created) URL.revokeObjectURL(created); };
  }, [src, token, visible]);
  if (failedSrc === src) return <span ref={host} className={className}>Image unavailable</span>;
  return objectUrl ? <img loading="lazy" className={className} src={objectUrl} alt={alt || "Screening image"} /> : <span ref={host} className={className}>{visible ? "Loading image…" : "Image loads when visible"}</span>;
}
