from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ...config import Config, get_config
from ...database import delete_preset, list_presets, save_preset

router = APIRouter(prefix="/presets")


class PresetBody(BaseModel):
    name: str
    settings: dict


@router.get("")
async def get_presets(config: Config = Depends(get_config)):
    return await list_presets(config.db_path)


@router.post("", status_code=201)
async def create_preset(body: PresetBody, config: Config = Depends(get_config)):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Preset name cannot be empty.")
    return await save_preset(config.db_path, name, body.settings)


@router.delete("/{preset_id}", status_code=204)
async def remove_preset(preset_id: str, config: Config = Depends(get_config)):
    deleted = await delete_preset(config.db_path, preset_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Preset not found.")
