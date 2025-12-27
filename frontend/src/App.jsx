import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { BrowserRouter as Router, Routes, Route, Link } from 'react-router-dom';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';

const API_URL = 'http://localhost:8000';

function Dashboard() {
  const [stats, setStats] = useState({ total_proxies: 0, active_proxies: 0, total_users: 0 });

  useEffect(() => {
    fetchStats();
  }, []);

  const fetchStats = async () => {
    try {
      const res = await axios.get(`${API_URL}/stats`);
      setStats(res.data);
    } catch (err) {
      console.error(err);
    }
  };

  const data = [
    { name: 'Mon', uv: 4000, pv: 2400, amt: 2400 },
    { name: 'Tue', uv: 3000, pv: 1398, amt: 2210 },
    { name: 'Wed', uv: 2000, pv: 9800, amt: 2290 },
    { name: 'Thu', uv: 2780, pv: 3908, amt: 2000 },
    { name: 'Fri', uv: 1890, pv: 4800, amt: 2181 },
    { name: 'Sat', uv: 2390, pv: 3800, amt: 2500 },
    { name: 'Sun', uv: 3490, pv: 4300, amt: 2100 },
  ];

  return (
    <div className="p-6">
      <h1 className="text-3xl font-bold mb-6">Dashboard</h1>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
        <div className="bg-white p-6 rounded-lg shadow-md">
          <h3 className="text-gray-500 text-sm">Total Proxies</h3>
          <p className="text-3xl font-bold">{stats.total_proxies}</p>
        </div>
        <div className="bg-white p-6 rounded-lg shadow-md">
          <h3 className="text-gray-500 text-sm">Active Proxies</h3>
          <p className="text-3xl font-bold text-green-600">{stats.active_proxies}</p>
        </div>
        <div className="bg-white p-6 rounded-lg shadow-md">
          <h3 className="text-gray-500 text-sm">Total Users</h3>
          <p className="text-3xl font-bold text-blue-600">{stats.total_users}</p>
        </div>
      </div>

      <div className="bg-white p-6 rounded-lg shadow-md">
        <h3 className="text-lg font-bold mb-4">Traffic Overview</h3>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" />
              <YAxis />
              <Tooltip />
              <Legend />
              <Line type="monotone" dataKey="pv" stroke="#8884d8" activeDot={{ r: 8 }} />
              <Line type="monotone" dataKey="uv" stroke="#82ca9d" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}

function Proxies() {
  const [proxies, setProxies] = useState([]);
  const [showModal, setShowModal] = useState(false);
  const [newProxy, setNewProxy] = useState({ port: 443, tag: '', server_ip: 'YOUR_IP' });

  useEffect(() => {
    fetchProxies();
  }, []);

  const fetchProxies = async () => {
    try {
      const res = await axios.get(`${API_URL}/proxies/`);
      setProxies(res.data);
    } catch (err) {
      console.error(err);
    }
  };

  const createProxy = async () => {
    try {
      await axios.post(`${API_URL}/proxies/`, newProxy);
      setShowModal(false);
      fetchProxies();
    } catch (err) {
      alert("Error creating proxy");
    }
  };

  const toggleProxy = async (id, status) => {
    try {
      if (status === 'running') {
        await axios.post(`${API_URL}/proxies/${id}/stop`);
      } else {
        await axios.post(`${API_URL}/proxies/${id}/start`);
      }
      fetchProxies();
    } catch (err) {
      alert("Error toggling proxy: " + err.response?.data?.detail || err.message);
    }
  };

  const addUser = async (proxyId) => {
    const name = prompt("Enter user name:");
    if (!name) return;
    try {
      await axios.post(`${API_URL}/proxies/${proxyId}/users/`, { name });
      fetchProxies();
      alert("User added! Proxy might be restarting...");
    } catch (err) {
      alert("Error adding user");
    }
  };

  return (
    <div className="p-6">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-3xl font-bold">Proxies</h1>
        <button 
          onClick={() => setShowModal(true)}
          className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700"
        >
          Create Proxy
        </button>
      </div>

      <div className="grid gap-6">
        {proxies.map(proxy => (
          <div key={proxy.id} className="bg-white p-6 rounded-lg shadow-md">
            <div className="flex justify-between items-start mb-4">
              <div>
                <h3 className="text-xl font-bold">Port: {proxy.port}</h3>
                <p className="text-gray-500">Tag: {proxy.tag || 'None'}</p>
                <p className="text-sm">Status: 
                  <span className={`ml-2 font-bold ${proxy.status === 'running' ? 'text-green-600' : 'text-red-600'}`}>
                    {proxy.status}
                  </span>
                </p>
              </div>
              <div className="space-x-2">
                <button 
                  onClick={() => toggleProxy(proxy.id, proxy.status)}
                  className={`px-3 py-1 rounded ${proxy.status === 'running' ? 'bg-red-100 text-red-600' : 'bg-green-100 text-green-600'}`}
                >
                  {proxy.status === 'running' ? 'Stop' : 'Start'}
                </button>
                <button 
                  onClick={() => addUser(proxy.id)}
                  className="bg-gray-100 text-gray-700 px-3 py-1 rounded"
                >
                  Add User
                </button>
              </div>
            </div>
            
            <div className="mt-4 border-t pt-4">
              <h4 className="font-bold text-sm mb-2">Users ({proxy.users?.length || 0})</h4>
              <div className="space-y-2">
                {proxy.users?.map(user => (
                  <div key={user.id} className="flex justify-between items-center text-sm bg-gray-50 p-2 rounded">
                    <span>{user.name}</span>
                    <span className="font-mono text-xs bg-gray-200 px-1 rounded">{user.secret.substring(0, 8)}...</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        ))}
      </div>

      {showModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center">
          <div className="bg-white p-6 rounded-lg w-96">
            <h2 className="text-xl font-bold mb-4">New Proxy</h2>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium">Port</label>
                <input 
                  type="number" 
                  value={newProxy.port}
                  onChange={e => setNewProxy({...newProxy, port: parseInt(e.target.value)})}
                  className="w-full border rounded p-2"
                />
              </div>
              <div>
                <label className="block text-sm font-medium">Ad Tag</label>
                <input 
                  type="text" 
                  value={newProxy.tag}
                  onChange={e => setNewProxy({...newProxy, tag: e.target.value})}
                  className="w-full border rounded p-2"
                />
              </div>
              <div>
                <label className="block text-sm font-medium">Server IP</label>
                <input 
                  type="text" 
                  value={newProxy.server_ip}
                  onChange={e => setNewProxy({...newProxy, server_ip: e.target.value})}
                  className="w-full border rounded p-2"
                />
              </div>
              <div className="flex justify-end space-x-2">
                <button onClick={() => setShowModal(false)} className="px-4 py-2 text-gray-600">Cancel</button>
                <button onClick={createProxy} className="px-4 py-2 bg-blue-600 text-white rounded">Create</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function App() {
  return (
    <Router>
      <div className="min-h-screen bg-gray-100 flex">
        <aside className="w-64 bg-gray-800 text-white">
          <div className="p-6">
            <h1 className="text-2xl font-bold">HoseinProxy</h1>
          </div>
          <nav className="mt-6">
            <Link to="/" className="block py-2.5 px-4 rounded transition duration-200 hover:bg-gray-700 hover:text-white">
              Dashboard
            </Link>
            <Link to="/proxies" className="block py-2.5 px-4 rounded transition duration-200 hover:bg-gray-700 hover:text-white">
              Proxies
            </Link>
          </nav>
        </aside>
        <main className="flex-1 overflow-y-auto">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/proxies" element={<Proxies />} />
          </Routes>
        </main>
      </div>
    </Router>
  );
}

export default App;
