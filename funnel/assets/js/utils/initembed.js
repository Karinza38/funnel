import addVegaSupport from './vegaembed';
import TypeformEmbed from './typeform_embed';
import MarkmapEmbed from './markmap';
import addMermaidEmbed from './mermaid';
import PrismEmbed from './prism';
import MarkdownMUITabs from './tabs';

export default function initEmbed(parentContainer = '.markdown') {
  TypeformEmbed.init(parentContainer);
  addVegaSupport(parentContainer);
  MarkmapEmbed.init(parentContainer);
  addMermaidEmbed(parentContainer);
  PrismEmbed.init(parentContainer);
  MarkdownMUITabs.init(parentContainer);
}
