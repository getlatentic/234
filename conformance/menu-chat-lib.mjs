// SPDX-License-Identifier: AGPL-3.0-or-later
// What the menu runs in the real chat page share: the two cards by their frame titles, asking for the menu,
// and the words of the thread outside its frames (a card's own words are not the model's).
import { cardIn, startChat, say, settled } from "./lib.mjs";

// A frame is titled after its card once the card has introduced itself, so the view a frame shows is found by its address.
const VIEWS = { Menu: "menu.html", Approval: "card.html" };
const frameOf = (title) => `card-frame[data-uri$="/${VIEWS[title]}"] iframe`;
export const menuFrame = (page) => cardIn(page, frameOf("Menu"));
export const approvalFrame = (page) => cardIn(page, frameOf("Approval"));
export const cardCount = (page, title) => page.locator(frameOf(title)).count();

export async function askForTheMenu(page) {
  const chat = await startChat(page, "What is on the menu?");
  await menuFrame(page).getByRole("searchbox", { name: "Search the menu" }).waitFor({ timeout: 20000 });
  await page.getByText("Pick what you like on the card.").waitFor({ timeout: 20000 });
  await settled(page, 10000);
  return chat;
}

/** The thread's text with every card removed: what a person reads in the conversation itself. */
export const threadText = (page) =>
  page.locator('[data-slot="thread"]').evaluate((thread) => {
    const copy = thread.cloneNode(true);
    copy.querySelectorAll("card-frame, script, template").forEach((node) => node.remove());
    return copy.innerText;
  });

export async function pickAndReview(page, { area = "Surulere", names = ["Bottled water, 75cl", "Puff puff, 6 pieces"] } = {}) {
  const frame = menuFrame(page);
  for (const name of names) await frame.getByRole("button", { name: `Add ${name}`, exact: true }).click();
  await frame.getByRole("button", { name: `One more ${names[0]}`, exact: true }).click();
  await frame.getByLabel("Deliver to").selectOption(area);
  await frame.getByRole("button", { name: "Review order" }).click();
}

export { say };
