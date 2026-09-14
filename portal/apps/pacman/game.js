// ComputeMesh Authentic 1980 Namco Pac-Man Arcade Engine
// Original 28x31 Grid, Direction Buffering (Pre-Turn Queueing), Zero-Sticking Motion & Authentic Konami 8-Bit Synthesizer

const canvas = document.getElementById('gameCanvas');
const ctx = canvas.getContext('2d');

const TILE_SIZE = 12;
const COLS = 28;
const ROWS = 31;
canvas.width = COLS * TILE_SIZE;
canvas.height = ROWS * TILE_SIZE;

// Original 1980 Arcade Grid: 
// 0 = Empty Corridor, 1 = Wall, 2 = Dot (Pellet), 3 = Energizer (Power Pellet), 4 = Ghost House, 5 = Ghost Gate
const ORIGINAL_MAP = [
  [1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],
  [1,2,2,2,2,2,2,2,2,2,2,2,2,1,1,2,2,2,2,2,2,2,2,2,2,2,2,1],
  [1,2,1,1,1,1,2,1,1,1,1,1,2,1,1,2,1,1,1,1,1,2,1,1,1,1,2,1],
  [1,3,1,1,1,1,2,1,1,1,1,1,2,1,1,2,1,1,1,1,1,2,1,1,1,1,3,1],
  [1,2,1,1,1,1,2,1,1,1,1,1,2,1,1,2,1,1,1,1,1,2,1,1,1,1,2,1],
  [1,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,1],
  [1,2,1,1,1,1,2,1,1,2,1,1,1,1,1,1,1,1,2,1,1,2,1,1,1,1,2,1],
  [1,2,1,1,1,1,2,1,1,2,1,1,1,1,1,1,1,1,2,1,1,2,1,1,1,1,2,1],
  [1,2,2,2,2,2,2,1,1,2,2,2,2,1,1,2,2,2,2,1,1,2,2,2,2,2,2,1],
  [1,1,1,1,1,1,2,1,1,1,1,1,0,1,1,0,1,1,1,1,1,2,1,1,1,1,1,1],
  [0,0,0,0,0,1,2,1,1,1,1,1,0,1,1,0,1,1,1,1,1,2,1,0,0,0,0,0],
  [0,0,0,0,0,1,2,1,1,0,0,0,0,0,0,0,0,0,0,1,1,2,1,0,0,0,0,0],
  [0,0,0,0,0,1,2,1,1,0,1,1,1,5,5,1,1,1,0,1,1,2,1,0,0,0,0,0],
  [1,1,1,1,1,1,2,1,1,0,1,4,4,4,4,4,4,1,0,1,1,2,1,1,1,1,1,1],
  [0,0,0,0,0,0,2,0,0,0,1,4,4,4,4,4,4,1,0,0,0,2,0,0,0,0,0,0],
  [1,1,1,1,1,1,2,1,1,0,1,4,4,4,4,4,4,1,0,1,1,2,1,1,1,1,1,1],
  [0,0,0,0,0,1,2,1,1,0,1,1,1,1,1,1,1,1,0,1,1,2,1,0,0,0,0,0],
  [0,0,0,0,0,1,2,1,1,0,0,0,0,0,0,0,0,0,0,1,1,2,1,0,0,0,0,0],
  [0,0,0,0,0,1,2,1,1,0,1,1,1,1,1,1,1,1,0,1,1,2,1,0,0,0,0,0],
  [1,1,1,1,1,1,2,1,1,0,1,1,1,1,1,1,1,1,0,1,1,2,1,1,1,1,1,1],
  [1,2,2,2,2,2,2,2,2,2,2,2,2,1,1,2,2,2,2,2,2,2,2,2,2,2,2,1],
  [1,2,1,1,1,1,2,1,1,1,1,1,2,1,1,2,1,1,1,1,1,2,1,1,1,1,2,1],
  [1,2,1,1,1,1,2,1,1,1,1,1,2,1,1,2,1,1,1,1,1,2,1,1,1,1,2,1],
  [1,3,2,2,1,1,2,2,2,2,2,2,2,0,0,2,2,2,2,2,2,2,1,1,2,2,3,1],
  [1,1,1,2,1,1,2,1,1,2,1,1,1,1,1,1,1,1,2,1,1,2,1,1,2,1,1,1],
  [1,1,1,2,1,1,2,1,1,2,1,1,1,1,1,1,1,1,2,1,1,2,1,1,2,1,1,1],
  [1,2,2,2,2,2,2,1,1,2,2,2,2,1,1,2,2,2,2,1,1,2,2,2,2,2,2,1],
  [1,2,1,1,1,1,1,1,1,1,1,1,2,1,1,2,1,1,1,1,1,1,1,1,1,1,2,1],
  [1,2,1,1,1,1,1,1,1,1,1,1,2,1,1,2,1,1,1,1,1,1,1,1,1,1,2,1],
  [1,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,1],
  [1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1]
];

let map = JSON.parse(JSON.stringify(ORIGINAL_MAP));

// Game State
let score = 0;
let highScore = parseInt(localStorage.getItem('pacman_highscore') || '0', 10);
let lives = 5;
let level = 1;
let gameOver = false;
let gameRunning = false;
let roundTransition = false;
let frightenedTimer = 0;
let invulnerableTimer = 0;
let konamiActivated = false;
let totalPellets = 0;
let initialPelletCount = 0;
let lastFrameTime = performance.now();
let roundTimer = 0;
let wakaToggle = false;

// Fruit bonus icons per level
const FRUIT_ICONS = ['🍒', '🍓', '🍊', '🍎', '🍈', '🔔', '🔑'];

// ==========================================
// 8-Bit Konami Authentic Web Audio Engine
// ==========================================
let audioCtx = null;

function initAudio() {
  if (!audioCtx) {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  }
  if (audioCtx && audioCtx.state === 'suspended') {
    audioCtx.resume();
  }
}

// Low-level chip tone generator (Pulse/Square waves with volume ADSR)
function playChipTone(freq, duration, type = 'square', gainVal = 0.12, pitchSlideTo = null) {
  if (!audioCtx) return;
  try {
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(freq, audioCtx.currentTime);
    if (pitchSlideTo !== null) {
      osc.frequency.exponentialRampToValueAtTime(Math.max(20, pitchSlideTo), audioCtx.currentTime + duration);
    }
    gain.gain.setValueAtTime(gainVal, audioCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.0001, audioCtx.currentTime + duration);
    osc.connect(gain);
    gain.connect(audioCtx.destination);
    osc.start();
    osc.stop(audioCtx.currentTime + duration);
  } catch (e) {}
}

// 1. Authentic Alternating Waka-Waka
function playWaka() {
  wakaToggle = !wakaToggle;
  if (wakaToggle) {
    playChipTone(360, 0.08, 'triangle', 0.15, 520);
  } else {
    playChipTone(520, 0.08, 'square', 0.12, 340);
  }
}

// 2. Power Pellet Energizer Siren (Arcade High-Low Wobble)
function playPowerPelletSound() {
  playChipTone(750, 0.12, 'sawtooth', 0.14, 450);
}

// 3. Ghost Eaten Chiptune (Konami 8-bit multi-frequency crunch)
function playEatGhostSound() {
  if (!audioCtx) return;
  const tones = [300, 520, 780, 1100];
  tones.forEach((freq, idx) => {
    setTimeout(() => playChipTone(freq, 0.07, 'square', 0.18), idx * 45);
  });
}

// 4. Konami Classic Intro Fanfare (Iconic Arcade Melody)
function playIntroMusic() {
  if (!audioCtx) return;
  const melody = [
    { f: 493.88, d: 0.12 }, // B4
    { f: 987.77, d: 0.12 }, // B5
    { f: 739.99, d: 0.12 }, // F#5
    { f: 622.25, d: 0.12 }, // D#5
    { f: 987.77, d: 0.10 }, // B5
    { f: 739.99, d: 0.14 }, // F#5
    { f: 622.25, d: 0.22 }, // D#5
    { f: 523.25, d: 0.12 }, // C5
    { f: 1046.5, d: 0.12 }, // C6
    { f: 783.99, d: 0.12 }, // G5
    { f: 659.25, d: 0.12 }, // E5
    { f: 1046.5, d: 0.10 }, // C6
    { f: 783.99, d: 0.14 }, // G5
    { f: 659.25, d: 0.24 }, // E5
  ];
  let delay = 0;
  melody.forEach(note => {
    setTimeout(() => playChipTone(note.f, note.d, 'square', 0.16), delay);
    delay += note.d * 1000 + 20;
  });
}

// 5. Authentic Arcade Stepped Death Jingle (Descending Chromatic Pitch)
function playDeathSound() {
  if (!audioCtx) return;
  const chromatic = [587, 554, 523, 493, 466, 440, 415, 392, 370, 349, 330, 311, 293, 220, 140];
  chromatic.forEach((f, idx) => {
    setTimeout(() => playChipTone(f, 0.08, 'sawtooth', 0.16, f * 0.9), idx * 65);
  });
}

// 6. Round Win Stage Clear Fanfare
function playRoundWinSound() {
  if (!audioCtx) return;
  const notes = [523.25, 659.25, 783.99, 1046.50, 1318.51];
  notes.forEach((f, idx) => {
    setTimeout(() => playChipTone(f, 0.16, 'square', 0.18), idx * 110);
  });
}

// 7. Legendary Konami 1-UP / Powerup Chime
function playKonamiFanfare() {
  if (!audioCtx) return;
  const fanfare = [330, 392, 659, 523, 587, 784];
  fanfare.forEach((f, idx) => {
    setTimeout(() => playChipTone(f, 0.14, 'square', 0.22), idx * 80);
  });
}

// ==========================================
// Difficulty & Progression Formula
// ==========================================
function getLevelSpeeds() {
  const speedBonus = Math.min((level - 1) * 0.10, 1.0);
  const pacmanBase = 2.0 + speedBonus + (konamiActivated ? 1.2 : 0.0);
  const ghostBase = 1.2 + Math.min((level - 1) * 0.10, 1.0);
  const frightenedDuration = Math.max(450 - (level - 1) * 35, 200);
  return { pacmanSpeed: pacmanBase, ghostSpeed: ghostBase, frightenedDuration };
}

// ==========================================
// Entities & Positioning
// ==========================================
const pacman = {
  x: 13.5 * TILE_SIZE + TILE_SIZE / 2,
  y: 23 * TILE_SIZE + TILE_SIZE / 2,
  dirX: -1,
  dirY: 0,
  desiredDirX: -1,
  desiredDirY: 0,
  radius: 5.5,
  mouthAngle: 0.2,
  mouthSpeed: 0.03,
  mouthDir: 1,
  rotation: Math.PI
};

const ghosts = [
  { name: 'blinky', color: '#ef4444', x: 13.5 * TILE_SIZE, y: 11 * TILE_SIZE, dirX: -1, dirY: 0, inHouse: false, releaseDelay: 0, targetX: 0, targetY: 0 },
  { name: 'pinky', color: '#ec4899', x: 13.5 * TILE_SIZE, y: 14 * TILE_SIZE, dirX: 0, dirY: -1, inHouse: true, releaseDelay: 3.5, targetX: 0, targetY: 0 },
  { name: 'inky', color: '#06b6d4', x: 11.5 * TILE_SIZE, y: 14 * TILE_SIZE, dirX: 0, dirY: -1, inHouse: true, releaseDelay: 8.0, targetX: 0, targetY: 0 },
  { name: 'clyde', color: '#f97316', x: 15.5 * TILE_SIZE, y: 14 * TILE_SIZE, dirX: 0, dirY: -1, inHouse: true, releaseDelay: 14.0, targetX: 0, targetY: 0 }
];

function countPellets() {
  let count = 0;
  for (let r = 0; r < ROWS; r++) {
    for (let c = 0; c < COLS; c++) {
      if (map[r][c] === 2 || map[r][c] === 3) count++;
    }
  }
  return count;
}

totalPellets = countPellets();
initialPelletCount = totalPellets;

function resetPositions() {
  pacman.x = 13.5 * TILE_SIZE + TILE_SIZE / 2;
  pacman.y = 23 * TILE_SIZE + TILE_SIZE / 2;
  pacman.dirX = -1;
  pacman.dirY = 0;
  pacman.desiredDirX = -1;
  pacman.desiredDirY = 0;
  pacman.rotation = Math.PI;
  roundTimer = 0;
  invulnerableTimer = 120; // 2 seconds invulnerability grace shield

  ghosts[0].x = 13.5 * TILE_SIZE; ghosts[0].y = 11 * TILE_SIZE; ghosts[0].inHouse = false; ghosts[0].dirX = -1; ghosts[0].dirY = 0;
  ghosts[1].x = 13.5 * TILE_SIZE; ghosts[1].y = 14 * TILE_SIZE; ghosts[1].inHouse = true; ghosts[1].dirX = 0; ghosts[1].dirY = -1;
  ghosts[2].x = 11.5 * TILE_SIZE; ghosts[2].y = 14 * TILE_SIZE; ghosts[2].inHouse = true; ghosts[2].dirX = 0; ghosts[2].dirY = -1;
  ghosts[3].x = 15.5 * TILE_SIZE; ghosts[3].y = 14 * TILE_SIZE; ghosts[3].inHouse = true; ghosts[3].dirX = 0; ghosts[3].dirY = -1;
}

// Map collision checker
function isTileWalkable(col, row, isGhost = false, inHouse = false) {
  if (col < 0 || col >= COLS) return true; // Warp Tunnel
  if (row < 0 || row >= ROWS) return false;

  const tile = map[row][col];
  if (tile === 1) return false; // Wall
  if (tile === 4) return inHouse; // Ghost house only when exiting
  if (tile === 5) return isGhost; // Ghost gate: only ghosts can cross
  return true;
}

// =========================================================================
// Direction Buffering, Corner Pre-Turn Queue & Zero-Sticking Motion Engine
// =========================================================================
function updatePacman(delta) {
  const { pacmanSpeed, frightenedDuration } = getLevelSpeeds();
  const moveDist = pacmanSpeed * delta;

  if (invulnerableTimer > 0) invulnerableTimer -= delta;

  const curCol = Math.floor(pacman.x / TILE_SIZE);
  const curRow = Math.floor(pacman.y / TILE_SIZE);
  const tileCenterX = curCol * TILE_SIZE + TILE_SIZE / 2;
  const tileCenterY = curRow * TILE_SIZE + TILE_SIZE / 2;

  // 1. Process Desired Direction Buffer (Persistent until executed at next opening)
  if (pacman.desiredDirX !== 0 || pacman.desiredDirY !== 0) {
    // 180-degree instant reversal (always allowed anywhere in corridor)
    if (pacman.desiredDirX === -pacman.dirX && pacman.desiredDirY === -pacman.dirY) {
      pacman.dirX = pacman.desiredDirX;
      pacman.dirY = pacman.desiredDirY;
      pacman.desiredDirX = 0;
      pacman.desiredDirY = 0;
    } else {
      // Perpendicular turn (e.g. going Left/Right and user queued Down)
      // Check if the opening into desired direction is walkable
      const targetCol = curCol + pacman.desiredDirX;
      const targetRow = curRow + pacman.desiredDirY;

      if (isTileWalkable(targetCol, targetRow, false, false)) {
        // Distance from current position to junction centerline
        const distToCenter = Math.hypot(pacman.x - tileCenterX, pacman.y - tileCenterY);
        // Snapping window: if within half a tile, snap to center and turn!
        if (distToCenter <= Math.max(moveDist * 1.5, 6)) {
          pacman.x = tileCenterX;
          pacman.y = tileCenterY;
          pacman.dirX = pacman.desiredDirX;
          pacman.dirY = pacman.desiredDirY;
          pacman.desiredDirX = 0;
          pacman.desiredDirY = 0;
        }
      }
    }
  }

  // 2. Wall Detection & Auto-Cornering (Never stick or freeze at walls)
  const isWallAhead = !isTileWalkable(curCol + pacman.dirX, curRow + pacman.dirY, false, false);
  if (isWallAhead) {
    const pastCenterX = (pacman.dirX > 0 && pacman.x >= tileCenterX) || (pacman.dirX < 0 && pacman.x <= tileCenterX);
    const pastCenterY = (pacman.dirY > 0 && pacman.y >= tileCenterY) || (pacman.dirY < 0 && pacman.y <= tileCenterY);

    if (pastCenterX || pastCenterY || (pacman.dirX === 0 && pacman.dirY === 0)) {
      pacman.x = tileCenterX;
      pacman.y = tileCenterY;

      // Find available perpendicular openings around the bend
      const orthogonal = pacman.dirX !== 0 
        ? [{ dx: 0, dy: -1 }, { dx: 0, dy: 1 }] 
        : [{ dx: -1, dy: 0 }, { dx: 1, dy: 0 }];

      let chosenTurn = null;
      // Prioritize desiredDir if valid
      if (pacman.desiredDirX !== 0 || pacman.desiredDirY !== 0) {
        if (isTileWalkable(curCol + pacman.desiredDirX, curRow + pacman.desiredDirY, false, false)) {
          chosenTurn = { dx: pacman.desiredDirX, dy: pacman.desiredDirY };
          pacman.desiredDirX = 0;
          pacman.desiredDirY = 0;
        }
      }

      if (!chosenTurn) {
        const openTurns = orthogonal.filter(d => isTileWalkable(curCol + d.dx, curRow + d.dy, false, false));
        if (openTurns.length > 0) {
          chosenTurn = openTurns[0];
        }
      }

      if (chosenTurn) {
        pacman.dirX = chosenTurn.dx;
        pacman.dirY = chosenTurn.dy;
      } else {
        pacman.dirX = 0;
        pacman.dirY = 0;
      }
    }
  }

  // 3. Move Pac-Man and Lock Axis to Centerline (Zero Lip Friction / No Corner Sticking)
  if (pacman.dirX !== 0 || pacman.dirY !== 0) {
    pacman.x += pacman.dirX * moveDist;
    pacman.y += pacman.dirY * moveDist;

    // Perpendicular clamping: keeps Pac-Man perfectly in the center of the corridor
    if (pacman.dirX !== 0) {
      pacman.y = tileCenterY;
    } else if (pacman.dirY !== 0) {
      pacman.x = tileCenterX;
    }

    // Warp Tunnel Wrap (Row 14)
    if (pacman.x < 0) pacman.x = (COLS - 1) * TILE_SIZE;
    if (pacman.x > (COLS - 1) * TILE_SIZE) pacman.x = 0;

    // Rotation & Mouth animation
    if (pacman.dirX > 0) pacman.rotation = 0;
    if (pacman.dirX < 0) pacman.rotation = Math.PI;
    if (pacman.dirY > 0) pacman.rotation = Math.PI / 2;
    if (pacman.dirY < 0) pacman.rotation = -Math.PI / 2;

    pacman.mouthAngle += pacman.mouthSpeed * pacman.mouthDir * delta * (1 + level * 0.1);
    if (pacman.mouthAngle > 0.45 || pacman.mouthAngle < 0.05) pacman.mouthDir *= -1;
  }

  // 4. Eating Pellets & Power Pellets
  const eatCol = Math.floor(pacman.x / TILE_SIZE);
  const eatRow = Math.floor(pacman.y / TILE_SIZE);
  if (eatCol >= 0 && eatCol < COLS && eatRow >= 0 && eatRow < ROWS) {
    if (map[eatRow][eatCol] === 2) {
      map[eatRow][eatCol] = 0;
      score += 10;
      totalPellets--;
      playWaka();
      updateHUD();
    } else if (map[eatRow][eatCol] === 3) {
      map[eatRow][eatCol] = 0;
      score += 50;
      totalPellets--;
      frightenedTimer = frightenedDuration;
      playPowerPelletSound();
      updateHUD();
    }
  }

  // 5. Round Completed
  if (totalPellets <= 0 && !roundTransition) {
    roundTransition = true;
    level++;
    playRoundWinSound();
    document.getElementById('konamiBanner').style.display = 'block';
    document.getElementById('konamiBanner').innerText = `⚡ RUNDE ${level} ERREICHT! TEMPO ERHÖHT 🚀`;
    setTimeout(() => {
      map = JSON.parse(JSON.stringify(ORIGINAL_MAP));
      totalPellets = countPellets();
      initialPelletCount = totalPellets;
      resetPositions();
      roundTransition = false;
      if (!konamiActivated) {
        document.getElementById('konamiBanner').style.display = 'none';
      }
      updateHUD();
    }, 1200);
  }
}

// ==========================================
// Ghost AI Engine
// ==========================================
function updateGhosts(delta) {
  if (roundTransition) return;
  roundTimer += (delta / 60);

  if (frightenedTimer > 0) frightenedTimer -= delta;

  const { ghostSpeed } = getLevelSpeeds();
  const currentSpeed = (frightenedTimer > 0 ? ghostSpeed * 0.45 : ghostSpeed) * delta;

  ghosts.forEach(ghost => {
    // Release from ghost house
    if (ghost.inHouse) {
      const dotsEaten = initialPelletCount - totalPellets;
      const shouldRelease = roundTimer >= ghost.releaseDelay || dotsEaten >= (ghost.releaseDelay * 5);
      if (shouldRelease) {
        ghost.y -= 0.5 * delta;
        if (ghost.y <= 11 * TILE_SIZE) {
          ghost.inHouse = false;
          ghost.dirX = -1;
          ghost.dirY = 0;
        }
      }
      return;
    }

    // AI Targeting
    if (frightenedTimer > 0) {
      ghost.targetX = Math.floor(Math.random() * COLS) * TILE_SIZE;
      ghost.targetY = Math.floor(Math.random() * ROWS) * TILE_SIZE;
    } else if (ghost.name === 'blinky') {
      ghost.targetX = pacman.x;
      ghost.targetY = pacman.y;
    } else if (ghost.name === 'pinky') {
      ghost.targetX = pacman.x + pacman.dirX * 4 * TILE_SIZE;
      ghost.targetY = pacman.y + pacman.dirY * 4 * TILE_SIZE;
    } else if (ghost.name === 'inky') {
      ghost.targetX = pacman.x + (pacman.x - ghosts[0].x);
      ghost.targetY = pacman.y + (pacman.y - ghosts[0].y);
    } else if (ghost.name === 'clyde') {
      const dist = Math.hypot(ghost.x - pacman.x, ghost.y - pacman.y);
      if (dist > 8 * TILE_SIZE) {
        ghost.targetX = pacman.x;
        ghost.targetY = pacman.y;
      } else {
        ghost.targetX = 0;
        ghost.targetY = (ROWS - 1) * TILE_SIZE;
      }
    }

    // Decision at tile intersections
    const gCol = Math.floor(ghost.x / TILE_SIZE);
    const gRow = Math.floor(ghost.y / TILE_SIZE);
    const dirs = [{ x: 1, y: 0 }, { x: -1, y: 0 }, { x: 0, y: 1 }, { x: 0, y: -1 }];
    const validDirs = dirs.filter(d => {
      if (d.x === -ghost.dirX && d.y === -ghost.dirY) return false;
      return isTileWalkable(gCol + d.x, gRow + d.y, true, ghost.inHouse);
    });

    if (validDirs.length > 0) {
      validDirs.sort((a, b) => {
        const distA = Math.hypot((ghost.x + a.x * TILE_SIZE) - ghost.targetX, (ghost.y + a.y * TILE_SIZE) - ghost.targetY);
        const distB = Math.hypot((ghost.x + b.x * TILE_SIZE) - ghost.targetX, (ghost.y + b.y * TILE_SIZE) - ghost.targetY);
        return distA - distB;
      });
      ghost.dirX = validDirs[0].x;
      ghost.dirY = validDirs[0].y;
    }

    ghost.x += ghost.dirX * currentSpeed;
    ghost.y += ghost.dirY * currentSpeed;

    // Warp tunnel wrap for ghosts
    if (ghost.x < 0) ghost.x = (COLS - 1) * TILE_SIZE;
    if (ghost.x > (COLS - 1) * TILE_SIZE) ghost.x = 0;

    // Ghost Collisions with Pacman
    const distToPacman = Math.hypot((ghost.x + TILE_SIZE / 2) - pacman.x, (ghost.y + TILE_SIZE / 2) - pacman.y);
    if (distToPacman < TILE_SIZE * 0.55 && invulnerableTimer <= 0) {
      if (frightenedTimer > 0) {
        ghost.x = 13.5 * TILE_SIZE;
        ghost.y = 14 * TILE_SIZE;
        ghost.inHouse = true;
        ghost.releaseDelay = roundTimer + 4.0;
        score += 200 * level;
        playEatGhostSound();
        updateHUD();
      } else if (!konamiActivated) {
        lives--;
        playDeathSound();
        updateHUD();
        if (lives <= 0) {
          gameOver = true;
          gameRunning = false;
          document.getElementById('overlayMessage').style.display = 'flex';
          document.getElementById('overlayTitle').innerText = 'GAME OVER';
          document.getElementById('btnStart').innerText = 'NEUSTART';
        } else {
          resetPositions();
        }
      }
    }
  });
}

// ==========================================
// Canvas Drawing
// ==========================================
function drawMap() {
  for (let r = 0; r < ROWS; r++) {
    for (let c = 0; c < COLS; c++) {
      const tile = map[r][c];
      const x = c * TILE_SIZE;
      const y = r * TILE_SIZE;

      if (tile === 1) {
        ctx.fillStyle = '#0a1128';
        ctx.strokeStyle = '#2563eb';
        ctx.lineWidth = 1.5;
        ctx.fillRect(x, y, TILE_SIZE, TILE_SIZE);
        ctx.strokeRect(x + 0.5, y + 0.5, TILE_SIZE - 1, TILE_SIZE - 1);
      } else if (tile === 2) {
        ctx.fillStyle = '#ffb897';
        ctx.beginPath();
        ctx.arc(x + TILE_SIZE / 2, y + TILE_SIZE / 2, 1.8, 0, Math.PI * 2);
        ctx.fill();
      } else if (tile === 3) {
        ctx.fillStyle = (Date.now() % 400 < 200) ? '#fbbf24' : '#fff';
        ctx.beginPath();
        ctx.arc(x + TILE_SIZE / 2, y + TILE_SIZE / 2, 4.2, 0, Math.PI * 2);
        ctx.fill();
      } else if (tile === 5) {
        ctx.fillStyle = '#f472b6';
        ctx.fillRect(x, y + TILE_SIZE / 2 - 1.5, TILE_SIZE, 3);
      }
    }
  }
}

function drawPacman() {
  if (invulnerableTimer > 0 && Math.floor(Date.now() / 100) % 2 === 0) {
    return;
  }

  ctx.save();
  ctx.translate(pacman.x, pacman.y);
  ctx.rotate(pacman.rotation);

  ctx.fillStyle = konamiActivated ? '#f59e0b' : '#fbbf24';
  if (konamiActivated) {
    ctx.shadowColor = '#f59e0b';
    ctx.shadowBlur = 12;
  }
  ctx.beginPath();
  ctx.arc(0, 0, pacman.radius, pacman.mouthAngle * Math.PI, (2 - pacman.mouthAngle) * Math.PI);
  ctx.lineTo(0, 0);
  ctx.fill();
  ctx.restore();
}

function drawGhosts() {
  ghosts.forEach(ghost => {
    ctx.save();
    ctx.translate(ghost.x, ghost.y);

    let gColor = ghost.color;
    if (frightenedTimer > 0) {
      gColor = (frightenedTimer < 120 && Math.floor(Date.now() / 150) % 2 === 0) ? '#ffffff' : '#2563eb';
    }

    ctx.fillStyle = gColor;
    ctx.beginPath();
    ctx.arc(TILE_SIZE / 2, TILE_SIZE / 2 - 1.5, 4.8, Math.PI, 0, false);
    ctx.lineTo(TILE_SIZE / 2 + 4.8, TILE_SIZE / 2 + 5);
    ctx.lineTo(TILE_SIZE / 2 - 4.8, TILE_SIZE / 2 + 5);
    ctx.fill();

    // Eyes
    ctx.fillStyle = '#ffffff';
    ctx.beginPath();
    ctx.arc(TILE_SIZE / 2 - 1.8, TILE_SIZE / 2 - 1.5, 1.6, 0, Math.PI * 2);
    ctx.arc(TILE_SIZE / 2 + 1.8, TILE_SIZE / 2 - 1.5, 1.6, 0, Math.PI * 2);
    ctx.fill();

    ctx.fillStyle = '#000000';
    ctx.beginPath();
    ctx.arc(TILE_SIZE / 2 - 1.8 + ghost.dirX * 0.8, TILE_SIZE / 2 - 1.5 + ghost.dirY * 0.8, 0.9, 0, Math.PI * 2);
    ctx.arc(TILE_SIZE / 2 + 1.8 + ghost.dirX * 0.8, TILE_SIZE / 2 - 1.5 + ghost.dirY * 0.8, 0.9, 0, Math.PI * 2);
    ctx.fill();

    ctx.restore();
  });
}

function updateHUD() {
  document.getElementById('scoreVal').innerText = score;
  if (score > highScore) {
    highScore = score;
    localStorage.setItem('pacman_highscore', highScore.toString());
  }
  document.getElementById('highScoreVal').innerText = highScore;
  document.getElementById('livesVal').innerText = '❤️ '.repeat(Math.max(0, lives));

  const fruit = FRUIT_ICONS[Math.min(level - 1, FRUIT_ICONS.length - 1)];
  const levelElem = document.getElementById('levelVal');
  if (levelElem) {
    levelElem.innerText = `RUNDE ${level} ${fruit}`;
  }
}

function gameLoop(now) {
  if (!gameRunning) return;

  const dt = Math.min((now - lastFrameTime) / 1000, 0.05);
  lastFrameTime = now;
  const delta = dt * 60;

  ctx.fillStyle = '#03050c';
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  drawMap();
  updatePacman(delta);
  updateGhosts(delta);
  drawPacman();
  drawGhosts();

  requestAnimationFrame(gameLoop);
}

// ==========================================
// Konami Code Engine
// ==========================================
const KONAMI_CODE = ['ArrowUp', 'ArrowUp', 'ArrowDown', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'ArrowLeft', 'ArrowRight', 'b', 'a'];
let konamiIndex = 0;

function checkKonami(key) {
  if (key.toLowerCase() === KONAMI_CODE[konamiIndex].toLowerCase()) {
    konamiIndex++;
    if (konamiIndex === KONAMI_CODE.length) {
      activateKonamiMode();
      konamiIndex = 0;
    }
  } else {
    konamiIndex = 0;
  }
}

function activateKonamiMode() {
  konamiActivated = true;
  lives = 30;
  document.getElementById('konamiBanner').style.display = 'block';
  document.getElementById('konamiBanner').innerText = '🌟 KONAMI GOD MODE: 30 LEBEN & HYPER TURBO SPEED! 🌟';
  playKonamiFanfare();
  updateHUD();
}

// ==========================================
// Input Handlers (Mobile Touch & Keyboard)
// ==========================================
function queueDirection(dx, dy) {
  initAudio();
  pacman.desiredDirX = dx;
  pacman.desiredDirY = dy;
}

window.addEventListener('keydown', e => {
  initAudio();
  checkKonami(e.key);

  switch (e.key) {
    case 'ArrowUp':
    case 'w':
    case 'W':
      queueDirection(0, -1); e.preventDefault(); break;
    case 'ArrowDown':
    case 's':
    case 'S':
      queueDirection(0, 1); e.preventDefault(); break;
    case 'ArrowLeft':
    case 'a':
    case 'A':
      queueDirection(-1, 0); e.preventDefault(); break;
    case 'ArrowRight':
    case 'd':
    case 'D':
      queueDirection(1, 0); e.preventDefault(); break;
  }
});

// Mobile On-Screen D-Pad
document.getElementById('btnUp')?.addEventListener('click', () => queueDirection(0, -1));
document.getElementById('btnDown')?.addEventListener('click', () => queueDirection(0, 1));
document.getElementById('btnLeft')?.addEventListener('click', () => queueDirection(-1, 0));
document.getElementById('btnRight')?.addEventListener('click', () => queueDirection(1, 0));
document.getElementById('btnA')?.addEventListener('click', () => checkKonami('a'));
document.getElementById('btnB')?.addEventListener('click', () => checkKonami('b'));

// Direct Touch Swipe Anywhere on Canvas
let touchStartX = 0;
let touchStartY = 0;
canvas.addEventListener('touchstart', e => {
  initAudio();
  touchStartX = e.touches[0].clientX;
  touchStartY = e.touches[0].clientY;
}, { passive: true });

canvas.addEventListener('touchend', e => {
  const dx = e.changedTouches[0].clientX - touchStartX;
  const dy = e.changedTouches[0].clientY - touchStartY;
  if (Math.abs(dx) > Math.abs(dy)) {
    if (dx > 15) queueDirection(1, 0);
    else if (dx < -15) queueDirection(-1, 0);
  } else {
    if (dy > 15) queueDirection(0, 1);
    else if (dy < -15) queueDirection(0, -1);
  }
}, { passive: true });

document.getElementById('btnStart').addEventListener('click', () => {
  initAudio();
  playIntroMusic();
  score = 0;
  level = 1;
  lives = konamiActivated ? 30 : 5;
  gameOver = false;
  gameRunning = true;
  roundTransition = false;
  map = JSON.parse(JSON.stringify(ORIGINAL_MAP));
  totalPellets = countPellets();
  initialPelletCount = totalPellets;
  resetPositions();
  updateHUD();
  document.getElementById('overlayMessage').style.display = 'none';
  lastFrameTime = performance.now();
  requestAnimationFrame(gameLoop);
});

updateHUD();
