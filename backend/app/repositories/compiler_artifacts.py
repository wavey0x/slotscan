"""Raw compiler artifact persistence."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import CompilerArtifact
from app.models.domain import RawCompilerArtifact


class CompilerArtifactRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, artifact: RawCompilerArtifact) -> None:
        values = {
            "fingerprint": artifact.fingerprint,
            "language": artifact.language,
            "compiler_version": artifact.compiler_version,
            "pipeline": artifact.pipeline,
            "standard_input": artifact.standard_input,
            "compiler_output": artifact.compiler_output,
            "source_hashes": artifact.source_hashes,
        }
        stmt = insert(CompilerArtifact).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["fingerprint"],
            set_={
                key: value
                for key, value in values.items()
                if key != "fingerprint"
            },
        )
        await self.session.execute(stmt)
        await self.session.commit()

    async def get(self, fingerprint: str) -> RawCompilerArtifact | None:
        result = await self.session.execute(
            select(CompilerArtifact).where(CompilerArtifact.fingerprint == fingerprint)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return RawCompilerArtifact(
            fingerprint=row.fingerprint,
            language=row.language,
            compiler_version=row.compiler_version,
            pipeline=row.pipeline,
            standard_input=row.standard_input,
            compiler_output=row.compiler_output,
            source_hashes=row.source_hashes,
        )
