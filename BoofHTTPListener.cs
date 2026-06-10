/*
 * Boof HTTP Listener - NinjaTrader 8
 * Receives signals from web UI and executes in NinjaTrader
 * 
 * HTTP Endpoints:
 *   GET  /status     - Check if listener is active
 *   POST /signal     - Receive trade signal from web
 * 
 * Signal Format:
 *   {
 *     "symbol": "ES",
 *     "direction": "long",
 *     "strategy": "Boof24",
 *     "signalType": "IMPULSE",
 *     "entryPrice": 5200.00,
 *     "stopPrice": 5190.00,
 *     "targetPrice": 5220.00,
 *     "rValue": 10,
 *     "accelScore": 75
 *   }
 */

#region Using declarations
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;
using System.Windows;
using System.Windows.Input;
using NinjaTrader.Cbi;
using NinjaTrader.Gui;
using NinjaTrader.Gui.Chart;
using NinjaTrader.Gui.SuperDom;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript;
using NinjaTrader.Core.FloatingPoint;
using NinjaTrader.NinjaScript.DrawingTools;
using Newtonsoft.Json;
#endregion

namespace NinjaTrader.NinjaScript.Indicators
{
    public class BoofHTTPListener : Indicator
    {
        #region Variables
        private HttpListener httpListener;
        private Thread listenerThread;
        private bool isRunning = false;
        private int port = 8080;
        private string logFile = "";
        private Queue<Signal> signalQueue = new Queue<Signal>();
        private object queueLock = new object();
        
        public class Signal
        {
            public string Symbol { get; set; }
            public string Direction { get; set; }
            public string Strategy { get; set; }
            public string SignalType { get; set; }
            public double EntryPrice { get; set; }
            public double StopPrice { get; set; }
            public double TargetPrice { get; set; }
            public double RValue { get; set; }
            public int AccelScore { get; set; }
            public DateTime Timestamp { get; set; }
        }
        #endregion

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Description = "Boof HTTP Listener - Web to NT Bridge";
                Name = "BoofHTTPListener";
                Calculate = Calculate.OnBarClose;
                IsOverlay = true;
                DisplayInDataBox = true;
                DrawOnPricePanel = true;
                DrawHorizontalGridLines = true;
                DrawVerticalGridLines = true;
                PaintPriceMarkers = true;
                ScaleJustification = NinjaTrader.Gui.Chart.ScaleJustification.Right;
                IsSuspendedWhileInactive = true;
            }
            else if (State == State.Configure)
            {
                AddPlot(new Stroke(Color.Cyan, DashStyleHelper.Solid, 2), PlotStyle.Dot, "Signal");
            }
            else if (State == State.Historical)
            {
                // Start HTTP listener
                StartListener();
            }
            else if (State == State.Terminated)
            {
                // Stop HTTP listener
                StopListener();
            }
        }

        protected override void OnBarUpdate()
        {
            // Process any queued signals
            ProcessSignalQueue();
        }

        #region HTTP Listener

        private void StartListener()
        {
            try
            {
                httpListener = new HttpListener();
                httpListener.Prefixes.Add($"http://*:{port}/");
                httpListener.Prefixes.Add($"http://localhost:{port}/");
                httpListener.Prefixes.Add($"http://127.0.0.1:{port}/");
                
                httpListener.Start();
                isRunning = true;
                
                listenerThread = new Thread(new ThreadStart(ListenLoop));
                listenerThread.IsBackground = true;
                listenerThread.Start();
                
                Draw.TextFixed(this, "Status", $"Boof HTTP Listener\nPort: {port}\nStatus: RUNNING\n\nWaiting for signals...", TextPosition.TopLeft, Color.Lime, new SimpleFont("Arial", 12), Color.Transparent, Color.Transparent, 0);
                
                Log("Boof HTTP Listener started on port " + port, LogLevel.Information);
            }
            catch (Exception ex)
            {
                Draw.TextFixed(this, "Status", $"Boof HTTP Listener\nPort: {port}\nStatus: ERROR\n\n{ex.Message}", TextPosition.TopLeft, Color.Red, new SimpleFont("Arial", 12), Color.Transparent, Color.Transparent, 0);
                Log("Failed to start HTTP listener: " + ex.Message, LogLevel.Error);
            }
        }

        private void StopListener()
        {
            isRunning = false;
            
            try
            {
                httpListener?.Stop();
                httpListener?.Close();
                listenerThread?.Join(1000);
            }
            catch (Exception ex)
            {
                Log("Error stopping listener: " + ex.Message, LogLevel.Warning);
            }
            
            Log("Boof HTTP Listener stopped", LogLevel.Information);
        }

        private void ListenLoop()
        {
            while (isRunning && httpListener != null)
            {
                try
                {
                    IAsyncResult result = httpListener.BeginGetContext(new AsyncCallback(HandleRequest), httpListener);
                    result.AsyncWaitHandle.WaitOne();
                }
                catch (Exception ex)
                {
                    if (isRunning)
                    {
                        Log("Listener error: " + ex.Message, LogLevel.Error);
                    }
                }
            }
        }

        private void HandleRequest(IAsyncResult result)
        {
            if (!isRunning) return;
            
            HttpListenerContext context = null;
            
            try
            {
                context = httpListener.EndGetContext(result);
                HttpListenerRequest request = context.Request;
                HttpListenerResponse response = context.Response;
                
                string path = request.Url.AbsolutePath.ToLower();
                
                if (path == "/status")
                {
                    // Status check endpoint
                    SendResponse(response, 200, "{\"status\":\"running\",\"port\":" + port + "}");
                }
                else if (path == "/signal" && request.HttpMethod == "POST")
                {
                    // Signal receive endpoint
                    HandleSignal(request, response);
                }
                else
                {
                    SendResponse(response, 404, "{\"error\":\"Not found\"}");
                }
            }
            catch (Exception ex)
            {
                Log("Request handling error: " + ex.Message, LogLevel.Error);
                if (context != null)
                {
                    try
                    {
                        SendResponse(context.Response, 500, "{\"error\":\"Internal server error\"}");
                    }
                    catch { }
                }
            }
        }

        private void HandleSignal(HttpListenerRequest request, HttpListenerResponse response)
        {
            try
            {
                using (StreamReader reader = new StreamReader(request.InputStream, request.ContentEncoding))
                {
                    string body = reader.ReadToEnd();
                    Signal signal = JsonConvert.DeserializeObject<Signal>(body);
                    
                    if (signal == null)
                    {
                        SendResponse(response, 400, "{\"error\":\"Invalid signal format\"}");
                        return;
                    }
                    
                    // Validate signal
                    if (string.IsNullOrEmpty(signal.Symbol) || string.IsNullOrEmpty(signal.Direction))
                    {
                        SendResponse(response, 400, "{\"error\":\"Missing required fields\"}");
                        return;
                    }
                    
                    // Queue signal for execution on next bar
                    lock (queueLock)
                    {
                        signal.Timestamp = DateTime.Now;
                        signalQueue.Enqueue(signal);
                    }
                    
                    string msg = $"Signal received: {signal.Symbol} {signal.Direction} ({signal.Strategy})";
                    Log(msg, LogLevel.Information);
                    
                    SendResponse(response, 200, "{\"status\":\"accepted\",\"message\":\"Signal queued for execution\"}");
                }
            }
            catch (Exception ex)
            {
                SendResponse(response, 400, "{\"error\":\"" + ex.Message + "\"}");
            }
        }

        private void SendResponse(HttpListenerResponse response, int statusCode, string content)
        {
            try
            {
                byte[] buffer = Encoding.UTF8.GetBytes(content);
                response.StatusCode = statusCode;
                response.ContentType = "application/json";
                response.ContentLength64 = buffer.Length;
                response.OutputStream.Write(buffer, 0, buffer.Length);
                response.OutputStream.Close();
                response.Close();
            }
            catch { }
        }

        #endregion

        #region Signal Processing

        private void ProcessSignalQueue()
        {
            List<Signal> signalsToProcess = new List<Signal>();
            
            lock (queueLock)
            {
                while (signalQueue.Count > 0)
                {
                    signalsToProcess.Add(signalQueue.Dequeue());
                }
            }
            
            foreach (var signal in signalsToProcess)
            {
                ExecuteSignal(signal);
            }
        }

        private void ExecuteSignal(Signal signal)
        {
            try
            {
                // Check if symbol matches current chart
                string chartSymbol = Instrument.FullName;
                if (!chartSymbol.Contains(signal.Symbol))
                {
                    Log($"Signal symbol {signal.Symbol} doesn't match chart {chartSymbol}", LogLevel.Warning);
                    return;
                }
                
                // Check if already in position
                if (Position.MarketPosition != MarketPosition.Flat)
                {
                    Log("Already in position, skipping signal", LogLevel.Warning);
                    return;
                }
                
                // Calculate prices
                double entryPrice = signal.EntryPrice > 0 ? signal.EntryPrice : Close[0];
                double stopDistance = signal.RValue * TickSize;
                double targetDistance = signal.RValue * 2 * TickSize; // 2R target
                
                if (signal.Direction.ToLower() == "long")
                {
                    double stopPrice = signal.StopPrice > 0 ? signal.StopPrice : entryPrice - stopDistance;
                    double targetPrice = signal.TargetPrice > 0 ? signal.TargetPrice : entryPrice + targetDistance;
                    
                    EnterLong(1, $"Boof_{signal.Strategy}_Long");
                    ExitLongStopMarket(1, stopPrice, "SL", $"Boof_{signal.Strategy}_Long");
                    ExitLongLimit(1, targetPrice, "TP", $"Boof_{signal.Strategy}_Long");
                    
                    Draw.Text(this, $"Entry{CurrentBar}", true, 
                        $"Boof {signal.Strategy}\n{signal.SignalType}\nScore: {signal.AccelScore}", 
                        0, entryPrice, 10, Color.Lime, new SimpleFont("Arial", 10), 
                        TextAlignment.Center, Color.Transparent, Color.Transparent, 0);
                    
                    Log($"LONG Entry: {entryPrice:F2} | SL: {stopPrice:F2} | TP: {targetPrice:F2}", LogLevel.Information);
                }
                else if (signal.Direction.ToLower() == "short")
                {
                    double stopPrice = signal.StopPrice > 0 ? signal.StopPrice : entryPrice + stopDistance;
                    double targetPrice = signal.TargetPrice > 0 ? signal.TargetPrice : entryPrice - targetDistance;
                    
                    EnterShort(1, $"Boof_{signal.Strategy}_Short");
                    ExitShortStopMarket(1, stopPrice, "SL", $"Boof_{signal.Strategy}_Short");
                    ExitShortLimit(1, targetPrice, "TP", $"Boof_{signal.Strategy}_Short");
                    
                    Draw.Text(this, $"Entry{CurrentBar}", true, 
                        $"Boof {signal.Strategy}\n{signal.SignalType}\nScore: {signal.AccelScore}", 
                        0, entryPrice, -10, Color.Red, new SimpleFont("Arial", 10), 
                        TextAlignment.Center, Color.Transparent, Color.Transparent, 0);
                    
                    Log($"SHORT Entry: {entryPrice:F2} | SL: {stopPrice:F2} | TP: {targetPrice:F2}", LogLevel.Information);
                }
            }
            catch (Exception ex)
            {
                Log("Signal execution error: " + ex.Message, LogLevel.Error);
            }
        }

        #endregion

        #region Properties

        [NinjaScriptProperty]
        [Display(Name = "HTTP Port", Description = "Port for HTTP listener", Order = 1, GroupName = "Connection")]
        public int HttpPort
        {
            get { return port; }
            set { port = Math.Max(1024, Math.Min(65535, value)); }
        }

        #endregion
    }
}
