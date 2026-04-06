/**
 * Lattice Face Geometry
 *
 * Defines the vertex positions and edge connections for a minimal
 * wireframe face. Not a full human mesh — just the structural essence:
 * brow ridge, eye sockets, nose bridge, cheekbones, jaw, chin.
 *
 * All coordinates normalized to roughly -1..1 range.
 */

// Each vertex: [x, y, z]
export const FACE_VERTICES: [number, number, number][] = [
  // Forehead / Crown (0-7)
  [0, 1.3, 0.1],         // 0: top center
  [-0.35, 1.2, 0.15],    // 1: top left
  [0.35, 1.2, 0.15],     // 2: top right
  [-0.55, 1.0, 0.2],     // 3: temple left
  [0.55, 1.0, 0.2],      // 4: temple right
  [-0.3, 1.05, 0.3],     // 5: forehead left
  [0.3, 1.05, 0.3],      // 6: forehead right
  [0, 1.1, 0.35],        // 7: forehead center

  // Brow ridge (8-13)
  [-0.5, 0.75, 0.35],    // 8: brow outer left
  [-0.25, 0.8, 0.42],    // 9: brow inner left
  [0, 0.78, 0.44],       // 10: brow center (glabella)
  [0.25, 0.8, 0.42],     // 11: brow inner right
  [0.5, 0.75, 0.35],     // 12: brow outer right
  [-0.38, 0.78, 0.4],    // 13: brow mid left

  // Eye sockets (14-21)
  [-0.38, 0.65, 0.38],   // 14: eye top left
  [-0.2, 0.62, 0.4],     // 15: eye inner left
  [-0.48, 0.6, 0.32],    // 16: eye outer left
  [-0.35, 0.55, 0.36],   // 17: eye bottom left
  [0.38, 0.65, 0.38],    // 18: eye top right
  [0.2, 0.62, 0.4],      // 19: eye inner right
  [0.48, 0.6, 0.32],     // 20: eye outer right
  [0.35, 0.55, 0.36],    // 21: eye bottom right

  // Nose (22-27)
  [0, 0.6, 0.48],        // 22: nose bridge top
  [0, 0.45, 0.55],       // 23: nose bridge mid
  [0, 0.3, 0.58],        // 24: nose tip
  [-0.12, 0.25, 0.5],    // 25: nostril left
  [0.12, 0.25, 0.5],     // 26: nostril right
  [0, 0.22, 0.52],       // 27: nose base

  // Cheekbones (28-31)
  [-0.58, 0.45, 0.3],    // 28: cheek left high
  [0.58, 0.45, 0.3],     // 29: cheek right high
  [-0.55, 0.2, 0.28],    // 30: cheek left low
  [0.55, 0.2, 0.28],     // 31: cheek right low

  // Mouth (32-39)
  [-0.22, 0.08, 0.46],   // 32: mouth corner left
  [0.22, 0.08, 0.46],    // 33: mouth corner right
  [-0.1, 0.12, 0.5],     // 34: upper lip left
  [0, 0.13, 0.52],       // 35: upper lip center
  [0.1, 0.12, 0.5],      // 36: upper lip right
  [-0.1, 0.03, 0.49],    // 37: lower lip left
  [0, 0.01, 0.5],        // 38: lower lip center
  [0.1, 0.03, 0.49],     // 39: lower lip right

  // Jaw (40-47)
  [-0.55, 0.05, 0.22],   // 40: jaw left
  [0.55, 0.05, 0.22],    // 41: jaw right
  [-0.48, -0.15, 0.24],  // 42: jaw mid left
  [0.48, -0.15, 0.24],   // 43: jaw mid right
  [-0.35, -0.32, 0.3],   // 44: jaw lower left
  [0.35, -0.32, 0.3],    // 45: jaw lower right
  [-0.15, -0.42, 0.36],  // 46: chin left
  [0.15, -0.42, 0.36],   // 47: chin right

  // Chin (48)
  [0, -0.48, 0.38],      // 48: chin point

  // Neck hints (49-50)
  [-0.2, -0.6, 0.2],     // 49: neck left
  [0.2, -0.6, 0.2],      // 50: neck right
];

// Edge connections: pairs of vertex indices
export const FACE_EDGES: [number, number][] = [
  // Crown
  [0, 1], [0, 2], [1, 3], [2, 4], [1, 5], [2, 6],
  [5, 7], [6, 7], [0, 7],
  [3, 5], [4, 6],

  // Brow
  [5, 9], [6, 11], [7, 10],
  [3, 8], [8, 13], [13, 9], [9, 10], [10, 11], [11, 12], [4, 12],

  // Left eye
  [8, 16], [13, 14], [9, 15],
  [14, 15], [14, 16], [15, 17], [16, 17],

  // Right eye
  [12, 20], [11, 19], [18, 19],
  [18, 20], [19, 21], [20, 21],

  // Nose
  [10, 22], [15, 22], [19, 22],
  [22, 23], [23, 24], [24, 25], [24, 26],
  [25, 27], [26, 27], [25, 26],

  // Cheeks
  [16, 28], [28, 30], [17, 28],
  [20, 29], [29, 31], [21, 29],
  [30, 32], [31, 33],
  [28, 16], [29, 20],

  // Mouth
  [27, 35],
  [32, 34], [34, 35], [35, 36], [36, 33],
  [32, 37], [37, 38], [38, 39], [39, 33],
  [25, 32], [26, 33],

  // Jaw
  [30, 40], [31, 41],
  [40, 42], [41, 43],
  [42, 44], [43, 45],
  [44, 46], [45, 47],
  [46, 48], [47, 48],
  [32, 40], [33, 41],

  // Chin to neck
  [48, 49], [48, 50],
  [46, 49], [47, 50],
];

// Vertex groups for animation
export const VERTEX_GROUPS = {
  brow: [8, 9, 10, 11, 12, 13],
  leftEye: [14, 15, 16, 17],
  rightEye: [18, 19, 20, 21],
  nose: [22, 23, 24, 25, 26, 27],
  mouth: [32, 33, 34, 35, 36, 37, 38, 39],
  jaw: [40, 41, 42, 43, 44, 45, 46, 47, 48],
  cheeks: [28, 29, 30, 31],
  forehead: [0, 1, 2, 3, 4, 5, 6, 7],
} as const;

// Emotion offsets: vertex index → [dx, dy, dz] displacement
export type EmotionOffsets = Record<number, [number, number, number]>;

export const EMOTION_OFFSETS: Record<string, EmotionOffsets> = {
  neutral: {},

  happy: {
    // Cheeks up, mouth corners up
    28: [0, 0.04, 0.02], 29: [0, 0.04, 0.02],
    32: [-0.03, 0.06, 0.02], 33: [0.03, 0.06, 0.02],
    34: [0, 0.03, 0], 35: [0, 0.04, 0.01], 36: [0, 0.03, 0],
    // Slight brow lift
    9: [0, 0.02, 0], 10: [0, 0.02, 0], 11: [0, 0.02, 0],
  },

  thinking: {
    // Brow inner up, slight head tilt via asymmetric brow
    9: [0, 0.06, 0.02], 10: [0, 0.05, 0.02], 11: [0, 0.03, 0],
    // Eyes slightly narrowed
    17: [0, 0.02, 0], 21: [0, 0.02, 0],
    // Mouth slightly compressed
    35: [0, -0.02, 0], 38: [0, 0.02, 0],
  },

  serious: {
    // Brows down and compressed
    8: [0, -0.04, 0.02], 9: [0.02, -0.05, 0.02],
    10: [0, -0.04, 0.02],
    11: [-0.02, -0.05, 0.02], 12: [0, -0.04, 0.02],
    // Mouth tense
    32: [0.02, 0, 0], 33: [-0.02, 0, 0],
    35: [0, -0.02, 0],
  },

  confused: {
    // Asymmetric brow — one up, one down
    8: [0, -0.02, 0], 9: [0, -0.01, 0],
    11: [0, 0.06, 0.02], 12: [0, 0.05, 0.01],
    // Mouth slightly open, off-center
    35: [0.02, 0.02, 0],
    38: [0.02, -0.04, 0],
    37: [0, -0.03, 0], 39: [0, -0.03, 0],
  },

  speaking: {
    // Jaw drops, mouth opens
    38: [0, -0.06, 0], 37: [-0.01, -0.05, 0], 39: [0.01, -0.05, 0],
    46: [0, -0.04, 0], 47: [0, -0.04, 0], 48: [0, -0.06, 0],
    44: [0, -0.03, 0], 45: [0, -0.03, 0],
    32: [-0.02, -0.02, 0], 33: [0.02, -0.02, 0],
  },
};
