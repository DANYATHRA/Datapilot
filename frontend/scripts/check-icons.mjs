import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const srcDir = path.resolve(__dirname, "../src");

// Regex matching common emojis and forbidden UI unicode glyphs
// Examples forbidden: 🎉 ⚠ ● ▲ ▼ ✓ ≈ ▤ ✎ × → 📁 📊 📗 📄 📦 💡 🛡️ 📥 👤 ✉️ ℹ️ ⚡ 📋 📜 🔗
const FORBIDDEN_PATTERN = /[\u{1F300}-\u{1F9FF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}\u{1F600}-\u{1F64F}\u{1F680}-\u{1F6FF}●▲▼✓≈▤✎×→←↑↓]/u;

// Forbidden sparkle/magic icons
const FORBIDDEN_LUCIDE_ICONS = ["Sparkles", "Wand", "Wand2", "MagicWand"];

function walkDir(dir, fileList = []) {
  const files = fs.readdirSync(dir);
  for (const file of files) {
    const fullPath = path.join(dir, file);
    const stat = fs.statSync(fullPath);
    if (stat.isDirectory()) {
      walkDir(fullPath, fileList);
    } else if (file.endsWith(".jsx") || (file.endsWith(".js") && !file.includes(".test."))) {
      fileList.push(fullPath);
    }
  }
  return fileList;
}

const files = walkDir(srcDir);
let violations = 0;

for (const f of files) {
  const content = fs.readFileSync(f, "utf8");
  const lines = content.split("\n");

  lines.forEach((line, idx) => {
    // Ignore lines that are comments or regex definitions or sample data strings
    if (line.trim().startsWith("//") || line.trim().startsWith("/*") || line.includes("FORBIDDEN_PATTERN") || line.includes("FORBIDDEN_LUCIDE_ICONS")) {
      return;
    }

    const match = line.match(FORBIDDEN_PATTERN);
    if (match) {
      console.error(`Forbidden icon/symbol '${match[0]}' in ${path.relative(srcDir, f)}:${idx + 1}`);
      console.error(`  > ${line.trim()}`);
      violations++;
    }

    // Check for forbidden sparkle / magic icons imported or rendered
    for (const iconName of FORBIDDEN_LUCIDE_ICONS) {
      // e.g. import { Sparkles } or <Sparkles
      const iconRegex = new RegExp(`\\b${iconName}\\b`);
      if (iconRegex.test(line) && !line.includes("FORBIDDEN")) {
        console.error(`Forbidden decorative sparkle icon '${iconName}' in ${path.relative(srcDir, f)}:${idx + 1}`);
        console.error(`  > ${line.trim()}`);
        violations++;
      }
    }
  });
}

if (violations > 0) {
  console.error(`\nFAILED: Found ${violations} forbidden emoji/Unicode/sparkle symbols in frontend/src.`);
  console.error("All UI icons must use professional 'lucide-react' icons only without decorative sparkles or Unicode emoji.\n");
  process.exit(1);
} else {
  console.log("PASSED: No forbidden emoji or decorative sparkle icons found in frontend/src.");
  process.exit(0);
}
