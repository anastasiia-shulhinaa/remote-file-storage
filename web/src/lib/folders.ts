import type { Folder, Uuid } from "../api/types";

export interface TreeNode {
  folder: Folder;
  children: TreeNode[];
}

/** Builds the folder tree from the flat list returned by GET /folders. */
export function buildTree(folders: Folder[]): TreeNode[] {
  const nodes = new Map<Uuid, TreeNode>(folders.map((folder) => [folder.id, { folder, children: [] }]));
  const roots: TreeNode[] = [];
  for (const node of nodes.values()) {
    const parent = node.folder.parent_folder_id ? nodes.get(node.folder.parent_folder_id) : undefined;
    (parent ? parent.children : roots).push(node);
  }
  const sort = (list: TreeNode[]) => {
    list.sort((a, b) => a.folder.name.localeCompare(b.folder.name));
    list.forEach((n) => sort(n.children));
  };
  sort(roots);
  return roots;
}

/** Root → … → folder. */
export function breadcrumbs(folders: Folder[], folderId: Uuid | null): Folder[] {
  const byId = new Map(folders.map((f) => [f.id, f]));
  const chain: Folder[] = [];
  let current = folderId ? byId.get(folderId) : undefined;
  while (current && chain.length < 100) {
    chain.unshift(current);
    current = current.parent_folder_id ? byId.get(current.parent_folder_id) : undefined;
  }
  return chain;
}

/** The root folder is the Virtual Disk itself: it is shown under the localized "My Drive" label. */
export function folderLabel(folder: Folder, rootLabel: string): string {
  return folder.parent_folder_id === null ? rootLabel : folder.name;
}

/** "My Drive / labs / lab1" for every folder, sorted by path (for selects). */
export function folderPaths(folders: Folder[], rootLabel: string): { id: Uuid; path: string }[] {
  return folders
    .map((f) => ({
      id: f.id,
      path: breadcrumbs(folders, f.id)
        .map((c) => folderLabel(c, rootLabel))
        .join(" / "),
    }))
    .sort((a, b) => a.path.localeCompare(b.path));
}
