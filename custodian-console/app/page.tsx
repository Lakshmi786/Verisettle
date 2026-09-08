import { RunList } from "./run-list";

export default function Home() {
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Live invoice pipeline</h1>
      <p className="text-sm text-neutral-400">
        Every run below is a real LangGraph checkpointed thread, polled directly from custodian-backend.
      </p>
      <RunList />
    </div>
  );
}
