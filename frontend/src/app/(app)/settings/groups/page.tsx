import type { Metadata } from "next";
import { GroupsPage } from "@/components/settings/groups-page";

export const metadata: Metadata = { title: "Server groups" };

export default function GroupsRoute() {
  return <GroupsPage />;
}
