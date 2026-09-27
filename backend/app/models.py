from dataclasses import dataclass


@dataclass
class Repository:
    id: int
    github_id: int
    full_name: str
    name: str
    owner: str
    description: str | None
    language: str | None
    visibility: str | None
    private: bool
    archived: bool
    fork: bool
    stars: int
    forks: int
    open_issues: int
    default_branch: str | None
    updated_at: str | None
    pushed_at: str | None
    synced_at: str


@dataclass
class Event:
    id: int
    repo_full_name: str
    event_type: str
    title: str
    actor: str | None
    url: str | None
    created_at: str
