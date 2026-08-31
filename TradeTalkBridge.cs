using System;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Threading.Tasks;
using System.Globalization;
using cAlgo.API;
using cAlgo.API.Internals;

namespace cAlgo.Robots
{
    [Robot(TimeZone = TimeZones.UTC, AccessRights = AccessRights.FullAccess)]
    public class TradeTalkBridge : Robot
    {
        [Parameter("TradeTalk Server URL", DefaultValue = "https://multi-agent-trading-bot.onrender.com")]
        public string ServerUrl { get; set; }

        [Parameter("Poll Interval (Seconds)", DefaultValue = 2, MinValue = 1, MaxValue = 10)]
        public int PollIntervalSeconds { get; set; }

        [Parameter("Enable Auto Execution", DefaultValue = true)]
        public bool EnableAutoExecution { get; set; }

        private static readonly HttpClient httpClient = new HttpClient { Timeout = TimeSpan.FromSeconds(5) };

        protected override void OnStart()
        {
            ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12 | SecurityProtocolType.Tls11 | SecurityProtocolType.Tls;

            string currencyName = "USD";
            try
            {
                currencyName = Account.Asset != null ? Account.Asset.Name : Account.CurrencyName;
            }
            catch
            {
                currencyName = "USD";
            }

            Print("=================================================");
            Print("TradeTalk.AI Autonomous cBot Bridge Started");
            Print("Account ID: " + Account.Number);
            Print("Live Balance: " + Account.Balance + " " + currencyName);
            Print("Server: " + ServerUrl);
            Print("=================================================");

            // Send initial registration heartbeat
            SendAccountHeartbeat();

            // Start timer for continuous telemetry & order polling
            Timer.Start(PollIntervalSeconds);
        }

        protected override void OnTimer()
        {
            try
            {
                // 1. Send live account telemetry (Balance, Equity, Free Margin)
                SendAccountHeartbeat();

                // 2. Poll for approved AI trade signals to execute
                if (EnableAutoExecution)
                {
                    PollAndExecutePendingOrders();
                }
            }
            catch (Exception ex)
            {
                Print("Timer Error: " + ex.Message);
            }
        }

        private async void SendAccountHeartbeat()
        {
            try
            {
                string endpoint = ServerUrl.TrimEnd('/') + "/api/cbot/stream";
                string currencyName = Account.Asset != null ? Account.Asset.Name : (Account.CurrencyName ?? "USD");
                string broker = Account.BrokerName ?? "cTrader Live";

                string jsonPayload = string.Format(
                    CultureInfo.InvariantCulture,
                    "{{\"account_id\":\"{0}\",\"accountNumber\":\"{0}\",\"balance\":{1},\"equity\":{2},\"margin\":{3},\"free_margin\":{4},\"currency\":\"{5}\",\"broker\":\"{6}\"}}",
                    Account.Number,
                    Account.Balance,
                    Account.Equity,
                    Account.Margin,
                    Account.FreeMargin,
                    currencyName,
                    broker
                );

                var content = new StringContent(jsonPayload, Encoding.UTF8, "application/json");
                await httpClient.PostAsync(endpoint, content);
            }
            catch (Exception ex)
            {
                // Non-blocking telemetry log
            }
        }

        private async void PollAndExecutePendingOrders()
        {
            try
            {
                string endpoint = ServerUrl.TrimEnd('/') + "/api/cbot/orders";
                var response = await httpClient.GetAsync(endpoint);
                
                if (response.IsSuccessStatusCode)
                {
                    string jsonResponse = await response.Content.ReadAsStringAsync();
                    if (!string.IsNullOrEmpty(jsonResponse) && jsonResponse != "[]" && jsonResponse.Contains("symbol"))
                    {
                        ProcessOrdersJson(jsonResponse);
                    }
                }
            }
            catch (Exception ex)
            {
                // Non-blocking poll log
            }
        }

        private void ProcessOrdersJson(string json)
        {
            try
            {
                Print("[TradeTalk Signal Received]: " + json);

                string symbol = ExtractJsonValue(json, "symbol");
                string action = ExtractJsonValue(json, "action").ToUpperInvariant();
                string signalId = ExtractJsonValue(json, "id");

                double lotSize = 0.01;
                double.TryParse(ExtractJsonValue(json, "lot_size"), NumberStyles.Any, CultureInfo.InvariantCulture, out lotSize);
                if (lotSize <= 0) lotSize = 0.01;

                double sl = 0;
                double.TryParse(ExtractJsonValue(json, "sl"), NumberStyles.Any, CultureInfo.InvariantCulture, out sl);

                double tp = 0;
                double.TryParse(ExtractJsonValue(json, "tp"), NumberStyles.Any, CultureInfo.InvariantCulture, out tp);

                // Resolve Symbol in cTrader
                Symbol targetSymbol = Symbols.GetSymbol(symbol) ?? Symbols.GetSymbol(symbol + "m") ?? Symbols.GetSymbol(symbol + ".pro") ?? Symbol;
                TradeType tradeType = (action == "BUY") ? TradeType.Buy : TradeType.Sell;

                // Normalize Volume to cTrader Symbol Units
                double volumeInUnits = targetSymbol.NormalizeVolumeInUnits(lotSize * 100000);
                if (targetSymbol.Name.Contains("XAU") || targetSymbol.Name.Contains("GOLD"))
                {
                    volumeInUnits = targetSymbol.NormalizeVolumeInUnits(lotSize * 100);
                }

                Print(string.Format(CultureInfo.InvariantCulture, "Executing {0} {1} Units of {2} | Target SL: {3}, TP: {4}", tradeType, volumeInUnits, targetSymbol.Name, sl, tp));

                // Execute Market Order using clean unambiguous signature
                TradeResult result = ExecuteMarketOrder(tradeType, targetSymbol.Name, volumeInUnits, "TradeTalk.AI");

                if (result.IsSuccessful && result.Position != null)
                {
                    Position pos = result.Position;
                    Print("🟢 Trade Filled! Ticket: " + pos.Id + " @ " + pos.EntryPrice);

                    // Set exact StopLoss and TakeProfit prices on the live position
                    if (sl > 0 || tp > 0)
                    {
                        double? slPrice = sl > 0 ? (double?)sl : null;
                        double? tpPrice = tp > 0 ? (double?)tp : null;
                        ModifyPosition(pos, slPrice, tpPrice);
                    }

                    // Report execution confirmation back to TradeTalk API
                    ReportExecutionConfirmation(signalId, pos.Id, pos.EntryPrice, targetSymbol.Name, action);
                }
                else
                {
                    Print("❌ Order failed: " + result.Error);
                }
            }
            catch (Exception ex)
            {
                Print("Error executing order: " + ex.Message);
            }
        }

        private async void ReportExecutionConfirmation(string signalId, long positionId, double fillPrice, string symbol, string action)
        {
            try
            {
                string endpoint = ServerUrl.TrimEnd('/') + "/api/cbot/order-filled";
                string jsonPayload = string.Format(
                    CultureInfo.InvariantCulture,
                    "{{\"id\":\"{0}\",\"ticket_id\":\"CT_{1}\",\"position_id\":\"{1}\",\"fill_price\":{2},\"symbol\":\"{3}\",\"action\":\"{4}\",\"status\":\"FILLED\"}}",
                    signalId, positionId, fillPrice, symbol, action
                );

                var content = new StringContent(jsonPayload, Encoding.UTF8, "application/json");
                await httpClient.PostAsync(endpoint, content);
            }
            catch (Exception ex)
            {
                // Non-blocking report log
            }
        }

        private string ExtractJsonValue(string json, string key)
        {
            string search = "\"" + key + "\":";
            int idx = json.IndexOf(search, StringComparison.OrdinalIgnoreCase);
            if (idx == -1) return "";
            int start = idx + search.Length;
            while (start < json.Length && (json[start] == ' ' || json[start] == '\"')) start++;
            int end = start;
            while (end < json.Length && json[end] != '\"' && json[end] != ',' && json[end] != '}') end++;
            return json.Substring(start, end - start).Trim('\"', ' ');
        }

        protected override void OnStop()
        {
            Print("TradeTalk Bridge Stopped.");
        }
    }
}
