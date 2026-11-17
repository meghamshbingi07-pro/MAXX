import asyncio
import asyncpg


async def main():
    conn = await asyncpg.connect(
        user='postgres',
        password='postgres123',
        database='maxx_db',
        host='127.0.0.1',
        port=5433,
    )

    rows = await conn.fetch(
        "SELECT schemaname, tablename FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema') ORDER BY schemaname, tablename"
    )

    if not rows:
        print('No user tables found')
    else:
        for r in rows:
            print(f"{r['schemaname']}.{r['tablename']}")

    await conn.close()


if __name__ == '__main__':
    asyncio.run(main())
