"""
Network Relationship View API routes for the Insurance Fraud Detection Platform.
Provides endpoints for querying and building network/relationship graphs
between policyholders, claims, and other entities.
"""
import logging

from fastapi import APIRouter, HTTPException, Query

from src.api.database import supabase
from src.api.models import NetworkGraphResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/network", tags=["Network View"])


def _build_node(entity_type: str, entity_id: str, label: str, metadata: dict = None) -> dict:
    """Build a node dict for the network graph."""
    return {
        "id": entity_id,
        "type": entity_type,
        "label": label,
        "metadata": metadata or {},
    }


def _build_edge(rel: dict) -> dict:
    """Build an edge dict from a network_relationships row."""
    return {
        "id": rel["id"],
        "source": rel["entity_a_id"],
        "target": rel["entity_b_id"],
        "source_type": rel["entity_a_type"],
        "target_type": rel["entity_b_type"],
        "relationship_type": rel["relationship_type"],
        "strength": float(rel.get("strength", 1.0)),
    }


# PUBLIC_INTERFACE
@router.get(
    "",
    response_model=NetworkGraphResponse,
    summary="Get full network graph",
    description="Retrieve the complete network graph of entity relationships for visualization.",
)
def get_network_graph(
    limit: int = Query(100, description="Max relationships to return", ge=1, le=500),
):
    """Get the full network graph for visualization.

    Fetches relationships and resolves entity labels for nodes.

    Args:
        limit: Maximum number of relationships.

    Returns:
        NetworkGraphResponse with nodes and edges.
    """
    try:
        resp = supabase.table("network_relationships").select("*").limit(limit).execute()
        relationships = resp.data or []

        nodes_map = {}
        edges = []

        for rel in relationships:
            edges.append(_build_edge(rel))

            # Collect unique node IDs
            for prefix in ("a", "b"):
                etype = rel[f"entity_{prefix}_type"]
                eid = rel[f"entity_{prefix}_id"]
                key = f"{etype}:{eid}"
                if key not in nodes_map:
                    nodes_map[key] = _build_node(etype, eid, f"{etype} {eid[:8]}...")

        # Try to resolve labels for known entity types
        _resolve_node_labels(nodes_map)

        return NetworkGraphResponse(
            nodes=list(nodes_map.values()),
            edges=edges,
        )
    except Exception as e:
        logger.error(f"Error fetching network graph: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get network: {str(e)}")


# PUBLIC_INTERFACE
@router.get(
    "/entity/{entity_type}/{entity_id}",
    response_model=NetworkGraphResponse,
    summary="Get network for a specific entity",
    description="Retrieve the network graph centered on a specific entity (policyholder, claim, etc.).",
)
def get_entity_network(entity_type: str, entity_id: str):
    """Get the network graph for a specific entity.

    Args:
        entity_type: Type of entity (e.g., 'policyholder', 'claim').
        entity_id: UUID of the entity.

    Returns:
        NetworkGraphResponse centered on the entity.
    """
    try:
        resp = supabase.table("network_relationships").select("*").or_(
            f"entity_a_id.eq.{entity_id},entity_b_id.eq.{entity_id}"
        ).execute()
        relationships = resp.data or []

        nodes_map = {}
        edges = []

        # Add the central entity
        nodes_map[f"{entity_type}:{entity_id}"] = _build_node(
            entity_type, entity_id, f"{entity_type} {entity_id[:8]}..."
        )

        for rel in relationships:
            edges.append(_build_edge(rel))
            for prefix in ("a", "b"):
                etype = rel[f"entity_{prefix}_type"]
                eid = rel[f"entity_{prefix}_id"]
                key = f"{etype}:{eid}"
                if key not in nodes_map:
                    nodes_map[key] = _build_node(etype, eid, f"{etype} {eid[:8]}...")

        _resolve_node_labels(nodes_map)

        return NetworkGraphResponse(
            nodes=list(nodes_map.values()),
            edges=edges,
        )
    except Exception as e:
        logger.error(f"Error fetching entity network: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get entity network: {str(e)}")


# PUBLIC_INTERFACE
@router.get(
    "/claim/{claim_id}",
    response_model=NetworkGraphResponse,
    summary="Get network for a claim",
    description="Build a network graph centered on a specific claim, including its policyholder and related entities.",
)
def get_claim_network(claim_id: str):
    """Build a network graph around a specific claim.

    Includes the claim, its policyholder, and any related network relationships.

    Args:
        claim_id: UUID of the claim.

    Returns:
        NetworkGraphResponse with claim-centered network.
    """
    try:
        nodes_map = {}
        edges = []

        # Get the claim
        claim_resp = supabase.table("claims").select("*").eq("id", claim_id).execute()
        if not claim_resp.data:
            raise HTTPException(status_code=404, detail="Claim not found")
        claim = claim_resp.data[0]

        nodes_map[f"claim:{claim_id}"] = _build_node(
            "claim", claim_id, f"Claim {claim.get('claim_number', '')}",
            {"amount": claim.get("claim_amount"), "status": claim.get("status")}
        )

        # Add policyholder if linked
        ph_id = claim.get("policyholder_id")
        if ph_id:
            try:
                ph_resp = supabase.table("policyholders").select("*").eq("id", ph_id).execute()
                if ph_resp.data:
                    ph = ph_resp.data[0]
                    label = f"{ph.get('first_name', '')} {ph.get('last_name', '')}"
                    nodes_map[f"policyholder:{ph_id}"] = _build_node(
                        "policyholder", ph_id, label.strip(),
                        {"email": ph.get("email"), "city": ph.get("city")}
                    )
                    edges.append({
                        "id": f"auto-{claim_id}-{ph_id}",
                        "source": ph_id,
                        "target": claim_id,
                        "source_type": "policyholder",
                        "target_type": "claim",
                        "relationship_type": "filed",
                        "strength": 1.0,
                    })
            except Exception:
                pass

        # Add network relationships
        net_resp = supabase.table("network_relationships").select("*").or_(
            f"entity_a_id.eq.{claim_id},entity_b_id.eq.{claim_id}"
        ).execute()

        for rel in (net_resp.data or []):
            edges.append(_build_edge(rel))
            for prefix in ("a", "b"):
                etype = rel[f"entity_{prefix}_type"]
                eid = rel[f"entity_{prefix}_id"]
                key = f"{etype}:{eid}"
                if key not in nodes_map:
                    nodes_map[key] = _build_node(etype, eid, f"{etype} {eid[:8]}...")

        # Also check policyholder's network
        if ph_id:
            ph_net_resp = supabase.table("network_relationships").select("*").or_(
                f"entity_a_id.eq.{ph_id},entity_b_id.eq.{ph_id}"
            ).execute()
            for rel in (ph_net_resp.data or []):
                edges.append(_build_edge(rel))
                for prefix in ("a", "b"):
                    etype = rel[f"entity_{prefix}_type"]
                    eid = rel[f"entity_{prefix}_id"]
                    key = f"{etype}:{eid}"
                    if key not in nodes_map:
                        nodes_map[key] = _build_node(etype, eid, f"{etype} {eid[:8]}...")

        _resolve_node_labels(nodes_map)

        return NetworkGraphResponse(
            nodes=list(nodes_map.values()),
            edges=edges,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error building claim network: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to build claim network: {str(e)}")


def _resolve_node_labels(nodes_map: dict) -> None:
    """Try to resolve human-readable labels for nodes by querying entity tables."""
    for key, node in nodes_map.items():
        etype = node["type"]
        eid = node["id"]
        try:
            if etype == "policyholder":
                resp = supabase.table("policyholders").select("first_name,last_name").eq("id", eid).execute()
                if resp.data:
                    ph = resp.data[0]
                    node["label"] = f"{ph.get('first_name', '')} {ph.get('last_name', '')}".strip()
            elif etype == "claim":
                resp = supabase.table("claims").select("claim_number").eq("id", eid).execute()
                if resp.data:
                    node["label"] = resp.data[0].get("claim_number", node["label"])
            elif etype == "policy":
                resp = supabase.table("policies").select("policy_number").eq("id", eid).execute()
                if resp.data:
                    node["label"] = resp.data[0].get("policy_number", node["label"])
        except Exception:
            pass  # Keep the default label
