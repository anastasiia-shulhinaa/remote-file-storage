import { useEffect, useMemo, useState } from "react";
import type { Folder, Uuid } from "../api/types";
import { useI18n } from "../i18n/I18nProvider";
import { breadcrumbs, buildTree, folderLabel, type TreeNode } from "../lib/folders";
import { routeHref } from "../lib/router";
import { Icon } from "./Icon";

interface FolderTreeProps {
  folders: Folder[];
  activeId: Uuid | null;
  onNavigate?: () => void;
}

export function FolderTree({ folders, activeId, onNavigate }: FolderTreeProps) {
  const { t } = useI18n();
  const tree = useMemo(() => buildTree(folders), [folders]);
  const [expanded, setExpanded] = useState<Set<Uuid>>(() => new Set());

  // always reveal the active folder
  useEffect(() => {
    const chain = breadcrumbs(folders, activeId).map((f) => f.id);
    if (chain.length === 0) return;
    setExpanded((prev) => {
      if (chain.every((id) => prev.has(id))) return prev;
      return new Set([...prev, ...chain]);
    });
  }, [folders, activeId]);

  const toggle = (id: Uuid) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const renderNode = (node: TreeNode, depth: number) => {
    const { folder, children } = node;
    const isOpen = expanded.has(folder.id) || depth === 0;
    const isActive = folder.id === activeId;
    const label = folderLabel(folder, t("nav.myDrive"));
    return (
      <li key={folder.id}>
        <div className={`tree-row ${isActive ? "active" : ""}`} style={{ paddingLeft: `${0.4 + depth * 0.9}rem` }}>
          {children.length > 0 && depth > 0 ? (
            <button
              className={`tree-toggle ${isOpen ? "open" : ""}`}
              onClick={() => toggle(folder.id)}
              aria-label={label}
              aria-expanded={isOpen}
            >
              <Icon name="chevronRight" size={14} />
            </button>
          ) : (
            <span className="tree-toggle-spacer" />
          )}
          <a
            href={routeHref({ name: "drive", folderId: folder.id })}
            onClick={onNavigate}
            aria-current={isActive ? "page" : undefined}
          >
            <Icon name={depth === 0 ? "hardDrive" : "folder"} size={16} />
            <span className="truncate">{label}</span>
          </a>
        </div>
        {isOpen && children.length > 0 && <ul>{children.map((child) => renderNode(child, depth + 1))}</ul>}
      </li>
    );
  };

  return <ul className="tree">{tree.map((node) => renderNode(node, 0))}</ul>;
}
