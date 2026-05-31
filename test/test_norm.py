import re
import unicodedata

def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode("ascii").casefold()
    # Collapse multiple spaces and trim
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())

print(f"'{_norm('Wrong - Todd Terry Remix')}'")
print(f"'{_norm('Wrong (Todd Terry Remix)')}'")
print(f"'{_norm('Wrong - Todd Terry Remix [Edit]')}'")
