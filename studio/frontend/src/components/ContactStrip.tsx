import { mediaUrl } from "../lib/api";

export function ContactStrip({
  images,
  label,
}: {
  images: string[];
  label: string;
}) {
  const slots = Array.from({ length: 4 }, (_, index) => images[index]);
  return (
    <div className="contact-strip" aria-label={label}>
      {slots.map((url, index) =>
        url ? (
          <div className="contact-frame" key={`${url}-${index}`}>
            <img src={mediaUrl(url)} alt="" loading="lazy" />
          </div>
        ) : (
          <div className="contact-frame contact-empty" key={`empty-${index}`}>
            <span aria-hidden="true">—</span>
          </div>
        ),
      )}
    </div>
  );
}
