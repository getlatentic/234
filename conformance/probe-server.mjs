// SPDX-License-Identifier: AGPL-3.0-or-later
// The official TypeScript client (the one the TS host uses) against any MCP server URL: does it connect over
// Streamable HTTP, list tools with their app visibility, call one, and read the ui:// resource?
// usage: node conformance/probe-server.mjs URL TOOL 'JSON args' UI_URI
import { Client, StreamableHTTPClientTransport } from "@modelcontextprotocol/client";
import { getToolUiResourceUri, isToolVisibilityAppOnly } from "@modelcontextprotocol/ext-apps/app-bridge";

const [url, tool, args, uri] = process.argv.slice(2);
const client = new Client({ name: "probe", version: "0.1.0" });
await client.connect(new StreamableHTTPClientTransport(new URL(url)));
const tools = (await client.listTools()).tools;
console.log("tools:", tools.map((t) => `${t.name}${isToolVisibilityAppOnly(t) ? " (app-only)" : ""} -> ${getToolUiResourceUri(t) ?? "-"}`).join("; "));
const result = await client.callTool({ name: tool, arguments: JSON.parse(args) });
console.log("call:", result.isError ? "ERROR" : "ok", JSON.stringify(result.structuredContent), "meta.approvalToken:", result._meta?.approvalToken);
const read = await client.readResource({ uri });
console.log("resource:", read.contents[0].mimeType, read.contents[0].text.length, "chars");
await client.close();
