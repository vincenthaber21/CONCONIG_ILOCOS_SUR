#!/usr/bin/env node

/**
 * Script to clear Metro bundler and Expo caches
 * Run with: node clear-cache.js
 */

const fs = require('fs');
const path = require('path');

const dirsToClean = [
  '.expo',
  'node_modules/.cache',
  '.metro',
  '.expo-shared',
];

const filesToClean = [
  '.expo',
];

console.log('🧹 Cleaning caches...\n');

let cleanedCount = 0;
let errorCount = 0;

// Clean directories
dirsToClean.forEach(dir => {
  const fullPath = path.join(__dirname, dir);
  try {
    if (fs.existsSync(fullPath)) {
      fs.rmSync(fullPath, { recursive: true, force: true });
      console.log(`✅ Cleaned: ${dir}`);
      cleanedCount++;
    } else {
      console.log(`ℹ️  Not found: ${dir}`);
    }
  } catch (error) {
    console.error(`❌ Error cleaning ${dir}:`, error.message);
    errorCount++;
  }
});

// Clean files
filesToClean.forEach(file => {
  const fullPath = path.join(__dirname, file);
  try {
    if (fs.existsSync(fullPath)) {
      if (fs.statSync(fullPath).isFile()) {
        fs.unlinkSync(fullPath);
        console.log(`✅ Cleaned file: ${file}`);
        cleanedCount++;
      }
    }
  } catch (error) {
    console.error(`❌ Error cleaning ${file}:`, error.message);
    errorCount++;
  }
});

console.log(`\n✨ Done! Cleaned ${cleanedCount} items.`);
if (errorCount > 0) {
  console.log(`⚠️  ${errorCount} errors occurred.`);
}

console.log('\n💡 Tip: Run "npm start" or "npm run start:clear" to start with a fresh cache.');

